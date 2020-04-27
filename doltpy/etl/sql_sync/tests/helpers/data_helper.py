from datetime import datetime
import logging
from doltpy.etl.sql_sync.tools import TableMetadata, Column
from decimal import Decimal
from typing import List

logger = logging.getLogger(__name__)

TABLE_NAME = 'great_players'
BASE_TEST_DATA_INITIAL = [
    {'first_name': 'Novak',
     'last_name': 'Djokovic',
     'playing_style_desc': 'aggressive/baseline',
     'win_percentage': 83.0,
     'high_rank': 1,
     'turned_pro': datetime(2003, 1, 1)},
    {'first_name': 'Rafael',
     'last_name': 'Nadal',
     'playing_style_desc': 'aggressive/baseline',
     'win_percentage': 83.2,
     'high_rank': 1,
     'turned_pro': datetime(2001,1, 1)},
    {'first_name': 'Roger',
     'last_name': 'Federer',
     'playing_style_desc': 'aggressive/all-court',
     'win_percentage': 81.2,
     'high_rank': 1,
     'turned_pro': datetime(1998, 1, 1)}
]
BASE_TEST_DATA_APPEND_MULTIPLE_ROWS = [
    {'first_name': 'Stefanos',
     'last_name': 'Tsitsipas',
     'playing_style_desc': 'aggressive/all-court',
     'win_percentage': 67.6,
     'high_rank': 5,
     'turned_pro': datetime(2016, 1, 1)},
    {'first_name': 'Alexander',
     'last_name': 'Zverev',
     'playing_style_desc': 'aggressive/baseline',
     'win_percentage': 65.8,
     'high_rank': 3,
     'turned_pro': datetime(2013, 1, 1)},
    {'first_name': 'Dominic',
     'last_name': 'Thiem',
     'playing_style_desc': 'aggressive/baseline',
     'win_percentage': 65.1,
     'high_rank': 3,
     'turned_pro': datetime(2011, 1, 1)}
]
BASE_TEST_DATA_APPEND_SINGLE_ROW = [
    {'first_name': 'Andy',
     'last_name': 'Murray',
     'playing_style_desc': 'defensive/baseline',
     'win_percentage': 77.4,
     'high_rank': 1,
     'turned_pro': datetime(2005, 1, 1)}
]
BASE_TEST_DATA_UPDATE_SINGLE_ROW = [
    {'first_name': 'Andrew',
     'last_name': 'Murray',
     'playing_style_desc': 'defensive/baseline',
     'win_percentage': 77.4,
     'high_rank': 1,
     'turned_pro': datetime(2005, 1, 1)}
]

TEST_TABLE_COLUMNS = [Column('first_name', 'VARCHAR(256)', 'PRI'),
                      Column('last_name', 'VARCHAR(256)', 'PRI'),
                      Column('playing_style_desc', 'LONGTEXT'),
                      Column('win_percentage', 'DECIMAL'),
                      Column('high_rank', 'INT'),
                      Column('turned_pro', 'DATETIME')]
TEST_TABLE_METADATA = TableMetadata(TABLE_NAME, TEST_TABLE_COLUMNS)


def _row_dicts_to_tuples(row_dict):
    return [tuple(el[col.col_name] for col in TEST_TABLE_METADATA.columns) for el in row_dict]


TEST_DATA_INITIAL = _row_dicts_to_tuples(BASE_TEST_DATA_INITIAL)
TEST_DATA_APPEND_MULTIPLE_ROWS = _row_dicts_to_tuples(BASE_TEST_DATA_APPEND_MULTIPLE_ROWS)
TEST_DATA_APPEND = _row_dicts_to_tuples(BASE_TEST_DATA_APPEND_MULTIPLE_ROWS)
TEST_DATA_APPEND_SINGLE_ROW = _row_dicts_to_tuples(BASE_TEST_DATA_APPEND_SINGLE_ROW)
TEST_DATA_UPDATE_SINGLE_ROW = _row_dicts_to_tuples(BASE_TEST_DATA_UPDATE_SINGLE_ROW)


def get_data_for_comparison(conn):
    """
    Given a database connection (MySQL, Dolt MySQL, or Postgres) returns data with column values in the order of the
    columns sorted alphabetically on name.
    :param conn:
    :return:
    """
    query = '''
        SELECT
            {columns}
        FROM
            {table_name}
        ORDER BY first_name, last_name ASC;
    '''.format(columns=','.join(col.col_name for col in TEST_TABLE_METADATA.columns),
               table_name=TEST_TABLE_METADATA.name)
    cursor = conn.cursor()
    cursor.execute(query)
    return [tup for tup in cursor]


DROP_TEST_TABLE = 'DROP TABLE {table_name}'.format(table_name=TABLE_NAME)


def assert_tuple_array_equality(left: List[tuple], right: List[tuple]):
    """
    Compares two lists of tuples for equality ensuring that Decimal values returned by databases are properly cast to
    execute correct comparison. All lists are sorted sorted using the primary key of the test data, which requires the
    data come in a specified order.
    :param left:
    :param right:
    :return:
    """
    assert len(left) == len(right)
    failed = False

    if len(left) == 0 and len(right) == 0:
        return True

    # All data comes in with values in the order of their column sorted alphabetically, 0 and 2 correspond to the
    # position of the primary keys in this column sort.
    def sort_helper(tup: tuple) -> tuple:
        return tup[0], tup[2]

    left.sort(key=sort_helper)
    right.sort(key=sort_helper)

    for left_tup, right_tup in zip(left, right):
        for left_el, right_el in zip(left_tup, right_tup):
            if type(left_el) == float:
                left_el = Decimal(str(left_el))
            if left_el != right_el:
                logger.warning('Non identical values (left) {} != {} (right)'.format(left_el, right_el))
                failed = True

    if failed:
        raise AssertionError('Errors found')
    else:
        return True
