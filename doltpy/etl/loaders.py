from typing import Callable, List
import io
from doltpy.core.dolt import UPDATE, Dolt
import pandas as pd
import hashlib
import importlib
import logging

DoltTableWriter = Callable[[Dolt], str]
DoltLoader = Callable[[Dolt], str]
DoltLoaderBuilder = Callable[[], List[DoltLoader]]
DataframeTransformer = Callable[[pd.DataFrame], pd.DataFrame]
FileTransformer = Callable[[io.StringIO], io.StringIO]

logger = logging.getLogger(__name__)


def resolve_function(module_path: str):
    """
    Takes a string of the form you.module.member_containing_loaders and returns a list of loaders.
    :param module_path:
    :return:
    """
    path_els = module_path.split('.')
    assert len(path_els) >= 2, 'must be a fully qualified path'
    module_path, member_name = '.'.join(path_els[:-1]), path_els[-1]
    try:
        retrieved_module = importlib.import_module(module_path)
        if hasattr(retrieved_module, member_name):
            return getattr(retrieved_module, member_name)
        else:
            raise ValueError('Module {} does not have member {}'.format(module_path, member_name))
    except ModuleNotFoundError as e:
        logger.info('Could not load module {}, ensure that the package is installed'.format(module_path))
        raise e


def resolve_branch(branch: str, module_generator_path: str, default: str):
    if branch:
        return_value = branch
    elif module_generator_path:
        return_value = resolve_function(module_generator_path)()
    else:
        return_value = default

    logger.info('Using branch {}'.format(return_value))
    return return_value


def insert_unique_key(df: pd.DataFrame) -> pd.DataFrame:
    assert 'hash_id' not in df.columns and 'count' not in df.columns, 'Require hash_id and count not in df'
    ids = df.apply(lambda r: hashlib.md5(','.join([str(el) for el in r]).encode('utf-8')).hexdigest(), axis=1)
    with_id = df.assign(hash_id=ids).set_index('hash_id')
    count_by_id = with_id.groupby('hash_id').size()
    with_id.loc[:, 'count'] = count_by_id
    return with_id.reset_index()


def _apply_df_transformers(data: pd.DataFrame, transformers: List[DataframeTransformer]) -> pd.DataFrame:
    if not transformers:
        return data
    temp = data.copy()
    for transformer in transformers:
        temp = transformer(data)
    return temp


def _apply_file_transformers(data: io.StringIO, transformers: List[FileTransformer]) -> io.StringIO:
    data.seek(0)
    if not transformers:
        return data
    temp = transformers[0](data)
    for transformer in transformers[1:]:
        temp = transformer(temp)

    return temp


def get_bulk_table_writer(table: str,
                          get_data: Callable[[], io.StringIO],
                          pk_cols: List[str],
                          import_mode: str = None,
                          transformers: List[FileTransformer] = None) -> DoltTableWriter:
    """
    Returns a loader function that writes a file-like object to Dolt, the file must be a valid CSV file.
    :param table:
    :param get_data:
    :param pk_cols:
    :param import_mode:
    :param transformers:
    :return:
    """
    def inner(repo: Dolt):
        _import_mode = import_mode or ('create' if table not in repo.get_existing_tables() else 'update')
        data_to_load = _apply_file_transformers(get_data(), transformers)
        repo.bulk_import(table, data_to_load, pk_cols, import_mode=_import_mode)
        return table

    return inner


def get_df_table_writer(table: str,
                        get_data: Callable[[], pd.DataFrame],
                        pk_cols: List[str],
                        import_mode: str = None,
                        transformers: List[DataframeTransformer] = None) -> DoltTableWriter:
    """
    Returns a loader that writes the `pd.DataFrame` produced by get_data to Dolt.
    :param table:
    :param get_data:
    :param pk_cols:
    :param import_mode:
    :param transformers:
    :return:
    """
    def inner(repo: Dolt):
        _import_mode = import_mode or ('create' if table not in repo.get_existing_tables() else 'update')
        data_to_load = _apply_df_transformers(get_data(), transformers)
        repo.import_df(table, data_to_load, pk_cols, import_mode=_import_mode)
        return table

    return inner


def get_table_transfomer(get_data: Callable[[Dolt], pd.DataFrame],
                         target_table: str,
                         target_pk_cols: List[str],
                         transformer: DataframeTransformer,
                         import_mode: str = UPDATE):
    def inner(repo: Dolt):
        input_data = get_data(repo)
        transformed_data = transformer(input_data)
        repo.import_df(target_table, transformed_data, target_pk_cols, import_mode=import_mode)
        return target_table

    return inner


def get_dolt_loader(table_writers: List[DoltTableWriter],
                    commit: bool,
                    message: str,
                    branch: str = 'master',
                    transaction_mode: bool = None) -> DoltLoader:
    """
    Given a repo and a set of table loaders, run the table loaders and conditionally commit the results with the
    specified message on the specified branch. If transaction_mode is true then ensure all loaders/transformers are
    successful, or all are rolled back.
    :param table_writers:
    :param commit:
    :param message:
    :param branch:
    :param transaction_mode:
    :return: the branch written to
    """
    def inner(repo: Dolt):
        original_branch = repo.get_current_branch()

        if branch != original_branch and not commit:
            raise ValueError('If writes are to another branch, and commit is not True, writes will be lost')

        if repo.get_current_branch() != branch:
            logger.info('Current branch is {}, checking out {}'.format(repo.get_current_branch(), branch))
            if branch not in repo.get_branch_list():
                logger.info('{} does not exist, creating'.format(branch))
                repo.create_branch(branch)
            repo.checkout(branch)

        if transaction_mode:
            raise NotImplementedError('transaction_mode is not yet implemented')

        tables_updated = [writer(repo) for writer in table_writers]

        if commit:
            logger.info('Committing to repo located in {} for tables:\n{}'.format(repo.repo_dir, tables_updated))
            for table in tables_updated:
                repo.add_table_to_next_commit(table)
            repo.commit(message)

        if original_branch != repo.get_current_branch():
            logger.info('Checked out {} from {}, checking out {} to restore state'.format(repo.get_current_branch(),
                                                                                          original_branch,
                                                                                          original_branch))
            repo.checkout(original_branch)

        return branch

    return inner
