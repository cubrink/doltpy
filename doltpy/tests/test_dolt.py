import pytest
import os
from doltpy.dolt import Dolt, _execute
import shutil
import pandas as pd
import uuid
from typing import Tuple
from doltpy.tests.dolt_testing_fixtures import init_repo, REPO_DIR, REPO_DATA_DIR


@pytest.fixture
def create_test_data() -> str:
    path = str(uuid.uuid4())
    pd.DataFrame({'name': ['Rafael', 'Novak'], 'id': [1, 2]}).to_csv(path, index_label=False)
    yield path
    os.remove(path)


@pytest.fixture
def create_test_table(init_repo, create_test_data) -> Tuple[Dolt, str]:
    repo, path = init_repo, create_test_data
    repo.import_df('test_players', pd.read_csv(path), ['id'], create=True)
    yield repo, 'test_players'
    _execute(['dolt', 'table', 'rm', 'test_players'], REPO_DIR)


@pytest.fixture
def run_serve_mode(init_repo):
    repo = init_repo
    repo.start_server()
    yield
    repo.stop_server()


def test_init_new_repo():
    assert not os.path.exists(REPO_DATA_DIR)
    dolt = Dolt(REPO_DIR)
    dolt.init_new_repo()
    assert os.path.exists(REPO_DATA_DIR)
    shutil.rmtree(REPO_DATA_DIR)


def test_put_row(create_test_table):
    repo, test_table = create_test_table
    repo.put_row(test_table, {'name': 'Roger', 'id': 3})
    df = repo.read_table(test_table).to_pandas()
    assert 'Roger' in df['name'].tolist() and 3 in df['id'].tolist()


def test_commit(create_test_table):
    repo, test_table = create_test_table
    repo.add_table_to_next_commit(test_table)
    before_commit_count = len(list(repo.get_commits()))
    repo.commit('Julianna, the very serious intellectual')
    assert repo.repo_is_clean() and len(list(repo.get_commits())) == before_commit_count + 1


def test_get_dirty_tables(create_test_table):
    repo, test_table = create_test_table
    message = 'Committing test data'

    # Some test data
    initial = pd.DataFrame({'id': [1], 'name': ['Bianca'], 'role': ['Champion']})
    appended_row = {'name': 'Serena', 'id': 2, 'role': 'Runner-up'}

    # existing, not modified
    repo.add_table_to_next_commit(test_table)
    repo.commit(message)

    # existing, modified, staged
    modified_staged = 'modified_staged'
    repo.import_df(modified_staged, initial, ['id'], True)
    repo.add_table_to_next_commit(modified_staged)

    # existing, modified, unstaged
    modified_unstaged = 'modified_unstaged'
    repo.import_df(modified_unstaged, initial, ['id'], True)
    repo.add_table_to_next_commit(modified_unstaged)

    # Commit and modify data
    repo.commit(message)
    repo.put_row(modified_staged, appended_row)
    repo.add_table_to_next_commit(modified_staged)
    repo.put_row(modified_unstaged, appended_row)

    # created, staged
    created_staged = 'created_staged'
    repo.import_df(created_staged, initial, ['id'], True)
    repo.add_table_to_next_commit(created_staged)

    # created, unstaged
    created_unstaged = 'created_unstaged'
    repo.import_df(created_unstaged, initial, ['id'], True)

    new_tables, changes = repo.get_dirty_tables()

    assert new_tables[created_staged] and not new_tables[created_unstaged]
    assert changes[modified_staged] and not changes[modified_unstaged]


def test_clean_local(create_test_table):
    repo, test_table = create_test_table
    repo.clean_local()
    assert repo.repo_is_clean()


# TODO Python sends these back as strings, causing tests to fail
@pytest.mark.skip('Currently the SQL API returns DataFrame with strings instead of ints')
def test_sql_server(create_test_table, run_serve_mode):
    repo, test_table = create_test_table
    data = repo.pandas_read_sql('SELECT * FROM {}'.format(test_table))
    assert list(data['id']) == [1, 2]


def test_transform_table_create_target(create_test_table):
    repo, test_table = create_test_table

    def transformer(df: pd.DataFrame) -> pd.DataFrame:
        return df.assign(role='player')

    target_table = 'enriched_{}'.format(test_table)
    repo.create_derivded_table(test_table, target_table, ['id', 'role'], transformer)
    result = repo.read_table(target_table).to_pandas()
    assert len(result.loc[(result['name'] == 'Rafael') & (result['role'] == 'player')]) == 1


def test_transform_table_inplace(create_test_table):
    repo, test_table = create_test_table
    initial_record_count = len(repo.read_table(test_table))

    def transformer(df: pd.DataFrame) -> pd.DataFrame:
        return df.assign(name=df['name'].str.lower())

    repo.transform_table_inplace(test_table, ['id'], transformer)
    result = repo.read_table(test_table).to_pandas()
    assert initial_record_count == len(result)
    assert len(result.loc[(result['name'] == 'rafael') & (result['id'] == 1)]) == 1


def test_transform_to_existing_table(create_test_table):
    repo, test_table = create_test_table

    # Create a test aggregates table
    wins_table = 'wins_by_player'
    aggregates = pd.DataFrame({'player': ['Novak', 'Roger', 'Rafael'],
                               'wins': [1, 2, 1]})
    repo.import_df(wins_table, aggregates, ['player'], True)
    repo.add_table_to_next_commit(wins_table)

    # Create some raw match data
    raw_match_table = 'raw_matches'
    raw_matches = pd.DataFrame({'match_id': [1, 2, 3, 4, 5],
                                'winner': ['Novak', 'Roger', 'Roger', 'Rafael', 'Rafael']})
    repo.import_df(raw_match_table, raw_matches, ['match_id'], True)
    repo.add_table_to_next_commit(raw_match_table)

    # Commit the test data
    repo.commit('Committing test data')

    # Perform transformation to update aggreagtes table with new data
    def aggregator(df: pd.DataFrame) -> pd.DataFrame:
        return (df
                .groupby('winner')[['match_id']]
                .count()
                .reset_index()
                .rename(columns={'match_id': 'wins', 'winner': 'player'}))

    repo.transform_to_existing_table(raw_match_table, wins_table, ['player'], aggregator)
    repo.add_table_to_next_commit(wins_table)
    repo.commit('Committing update to {}'.format(wins_table))

    result = repo.read_table(wins_table).to_pandas()
    assert result.loc[result['player'] == 'Rafael', 'wins'].iloc[0] == 2