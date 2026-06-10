import re

import pytest

from tinydb import where


def test_next_id(db):
    db.truncate()

    assert db._get_next_id() == 1
    assert db._get_next_id() == 2
    assert db._get_next_id() == 3


def test_tables_list(db):
    db.table('table1').insert({'a': 1})
    db.table('table2').insert({'a': 1})

    assert db.tables() == {'_default', 'table1', 'table2'}


def test_one_table(db):
    table1 = db.table('table1')

    table1.insert_multiple({'int': 1, 'char': c} for c in 'abc')

    assert table1.get(where('int') == 1)['char'] == 'a'
    assert table1.get(where('char') == 'b')['char'] == 'b'


def test_multiple_tables(db):
    table1 = db.table('table1')
    table2 = db.table('table2')
    table3 = db.table('table3')

    table1.insert({'int': 1, 'char': 'a'})
    table2.insert({'int': 1, 'char': 'b'})
    table3.insert({'int': 1, 'char': 'c'})

    assert table1.count(where('char') == 'a') == 1
    assert table2.count(where('char') == 'b') == 1
    assert table3.count(where('char') == 'c') == 1

    db.drop_tables()

    with pytest.raises(RuntimeError):
        len(table1)
    with pytest.raises(RuntimeError):
        len(table2)
    with pytest.raises(RuntimeError):
        len(table3)


def test_caching(db):
    table1 = db.table('table1')
    table2 = db.table('table1')

    assert table1 is table2


def test_query_cache(db):
    query1 = where('int') == 1

    assert db.count(query1) == 3
    assert query1 in db._query_cache

    assert db.count(query1) == 3
    assert query1 in db._query_cache

    query2 = where('int') == 0

    assert db.count(query2) == 0
    assert query2 in db._query_cache

    assert db.count(query2) == 0
    assert query2 in db._query_cache


def test_query_cache_with_mutable_callable(db):
    table = db.table('table')
    table.insert({'val': 5})

    mutable = 5
    increase = lambda x: x + mutable

    assert where('val').is_cacheable()
    assert not where('val').map(increase).is_cacheable()
    assert not (where('val').map(increase) == 10).is_cacheable()

    search = where('val').map(increase) == 10
    assert table.count(search) == 1

    # now `increase` would yield 15, not 10
    mutable = 10

    assert table.count(search) == 0
    assert len(table._query_cache) == 0


def test_zero_cache_size(db):
    table = db.table('table3', cache_size=0)
    query = where('int') == 1

    table.insert({'int': 1})
    table.insert({'int': 1})

    assert table.count(query) == 2
    assert table.count(where('int') == 2) == 0
    assert len(table._query_cache) == 0


def test_query_cache_size(db):
    table = db.table('table3', cache_size=1)
    query = where('int') == 1

    table.insert({'int': 1})
    table.insert({'int': 1})

    assert table.count(query) == 2
    assert table.count(where('int') == 2) == 0
    assert len(table._query_cache) == 1


def test_lru_cache(db):
    # Test integration into TinyDB
    table = db.table('table3', cache_size=2)
    query = where('int') == 1

    table.search(query)
    table.search(where('int') == 2)
    table.search(where('int') == 3)
    assert query not in table._query_cache

    table.remove(where('int') == 1)
    assert not table._query_cache.lru

    table.search(query)

    assert len(table._query_cache) == 1
    table.clear_cache()
    assert len(table._query_cache) == 0


def test_table_is_iterable(db):
    table = db.table('table1')

    table.insert_multiple({'int': i} for i in range(3))

    assert [r for r in table] == table.all()


def test_table_name(db):
    name = 'table3'
    table = db.table(name)
    assert name == table.name

    with pytest.raises(AttributeError):
        table.name = 'foo'


def test_table_repr(db):
    name = 'table4'
    table = db.table(name)

    assert re.match(
        r"<Table name=\'table4\', total=0, "
        r"storage=<tinydb\.storages\.(MemoryStorage|JSONStorage) object at [a-zA-Z0-9]+>>",
        repr(table))


def test_truncate_table(db):
    db.truncate()
    assert db._get_next_id() == 1


def test_persist_table(db):
    db.table("persisted", persist_empty=True)
    assert "persisted" in db.tables()

    db.table("nonpersisted", persist_empty=False)
    assert "nonpersisted" not in db.tables()


def test_drop_table_invalidates_old_ref(db):
    table = db.table('mytable')
    table.insert({'x': 1})

    db.drop_table('mytable')

    with pytest.raises(RuntimeError):
        table.insert({'x': 2})

    with pytest.raises(RuntimeError):
        table.all()

    with pytest.raises(RuntimeError):
        table.search(where('x') == 1)

    with pytest.raises(RuntimeError):
        len(table)


def test_drop_table_new_ref_works(db):
    table_old = db.table('mytable')
    table_old.insert({'x': 1})

    db.drop_table('mytable')

    table_new = db.table('mytable')
    assert len(table_new) == 0
    table_new.insert({'y': 2})
    assert len(table_new) == 1


def test_drop_tables_invalidates_default_table_ref(db):
    default = db.table(db.default_table_name)
    default.insert({'a': 1})

    db.drop_tables()

    # Old reference is dead
    with pytest.raises(RuntimeError):
        default.insert({'a': 2})

    # Proxy API creates a fresh table and works fine
    db.insert({'b': 3})
    assert len(db) == 1


def test_drop_table_idempotent(db):
    table = db.table('mytable')
    table.insert({'x': 1})

    db.drop_table('mytable')
    db.drop_table('mytable')  # Second drop: no-op, no error

    with pytest.raises(RuntimeError):
        table.all()


def test_drop_table_repr_after_close(db):
    table = db.table('mytable')
    db.drop_table('mytable')

    r = repr(table)
    assert 'dropped' in r
    assert 'mytable' in r


def test_drop_table_name_property_after_close(db):
    table = db.table('mytable')
    db.drop_table('mytable')
    assert table.name == 'mytable'
