import json
import os
import random
import tempfile
from unittest.mock import patch

import pytest

from tinydb import TinyDB, where
from tinydb.storages import JSONStorage, MemoryStorage, Storage, touch
from tinydb.table import Document

random.seed()

doc = {'none': [None, None], 'int': 42, 'float': 3.1415899999999999,
       'list': ['LITE', 'RES_ACID', 'SUS_DEXT'],
       'dict': {'hp': 13, 'sp': 5},
       'bool': [True, False, True, False]}


def test_json(tmpdir):
    # Write contents
    path = str(tmpdir.join('test.db'))
    storage = JSONStorage(path)
    storage.write(doc)

    # Verify contents
    assert doc == storage.read()
    storage.close()


def test_json_kwargs(tmpdir):
    db_file = tmpdir.join('test.db')
    db = TinyDB(str(db_file), sort_keys=True, indent=4, separators=(',', ': '))

    # Write contents
    db.insert({'b': 1})
    db.insert({'a': 1})

    assert db_file.read() == '''{
    "_default": {
        "1": {
            "b": 1
        },
        "2": {
            "a": 1
        }
    }
}'''
    db.close()


def test_json_readwrite(tmpdir):
    """
    Regression test for issue #1
    """
    path = str(tmpdir.join('test.db'))

    # Create TinyDB instance
    db = TinyDB(path, storage=JSONStorage)

    item = {'name': 'A very long entry'}
    item2 = {'name': 'A short one'}

    def get(s):
        return db.get(where('name') == s)

    db.insert(item)
    assert get('A very long entry') == item

    db.remove(where('name') == 'A very long entry')
    assert get('A very long entry') is None

    db.insert(item2)
    assert get('A short one') == item2

    db.remove(where('name') == 'A short one')
    assert get('A short one') is None

    db.close()


def test_json_read(tmpdir):
    r"""Open a database only for reading"""
    path = str(tmpdir.join('test.db'))
    with pytest.raises(FileNotFoundError):
        db = TinyDB(path, storage=JSONStorage, access_mode='r')
    # Create small database
    db = TinyDB(path, storage=JSONStorage)
    db.insert({'b': 1})
    db.insert({'a': 1})
    db.close()
    # Access in read mode
    db = TinyDB(path, storage=JSONStorage, access_mode='r')
    assert db.get(where('a') == 1) == {'a': 1}  # reading is fine
    with pytest.raises(IOError):
        db.insert({'c': 1})  # writing is not
    db.close()


def test_create_dirs():
    temp_dir = tempfile.gettempdir()

    while True:
        dname = os.path.join(temp_dir, str(random.getrandbits(20)))
        if not os.path.exists(dname):
            db_dir = dname
            db_file = os.path.join(db_dir, 'db.json')
            break

    with pytest.raises(IOError):
        JSONStorage(db_file)

    JSONStorage(db_file, create_dirs=True).close()
    assert os.path.exists(db_file)

    # Use create_dirs with already existing directory
    JSONStorage(db_file, create_dirs=True).close()
    assert os.path.exists(db_file)

    os.remove(db_file)
    os.rmdir(db_dir)


def test_json_invalid_directory():
    with pytest.raises(IOError):
        with TinyDB('/this/is/an/invalid/path/db.json', storage=JSONStorage):
            pass


def test_in_memory():
    # Write contents
    storage = MemoryStorage()
    storage.write(doc)

    # Verify contents
    assert doc == storage.read()

    # Test case for #21
    other = MemoryStorage()
    other.write({})
    assert other.read() != storage.read()


def test_in_memory_close():
    with TinyDB(storage=MemoryStorage) as db:
        db.insert({})


def test_custom():
    # noinspection PyAbstractClass
    class MyStorage(Storage):
        pass

    with pytest.raises(TypeError):
        MyStorage()


def test_read_once():
    count = 0

    # noinspection PyAbstractClass
    class MyStorage(Storage):
        def __init__(self):
            self.memory = None

        def read(self):
            nonlocal count
            count += 1

            return self.memory

        def write(self, data):
            self.memory = data

    with TinyDB(storage=MyStorage) as db:
        assert count == 0

        db.table(db.default_table_name)

        assert count == 0

        db.all()

        assert count == 1

        db.insert({'foo': 'bar'})

        assert count == 3  # One for getting the next ID, one for the insert

        db.all()

        assert count == 4


def test_custom_with_exception():
    class MyStorage(Storage):
        def read(self):
            pass

        def write(self, data):
            pass

        def __init__(self):
            raise ValueError()

        def close(self):
            raise RuntimeError()

    with pytest.raises(ValueError):
        with TinyDB(storage=MyStorage) as db:
            pass


def test_yaml(tmpdir):
    """
    :type tmpdir: py._path.local.LocalPath
    """

    try:
        import yaml
    except ImportError:
        return pytest.skip('PyYAML not installed')

    def represent_doc(dumper, data):
        # Represent `Document` objects as their dict's string representation
        # which PyYAML understands
        return dumper.represent_data(dict(data))

    yaml.add_representer(Document, represent_doc)

    class YAMLStorage(Storage):
        def __init__(self, filename):
            self.filename = filename
            touch(filename, False)

        def read(self):
            with open(self.filename) as handle:
                data = yaml.safe_load(handle.read())
                return data

        def write(self, data):
            with open(self.filename, 'w') as handle:
                yaml.dump(data, handle)

        def close(self):
            pass

    # Write contents
    path = str(tmpdir.join('test.db'))
    db = TinyDB(path, storage=YAMLStorage)
    db.insert(doc)
    assert db.all() == [doc]

    db.update({'name': 'foo'})

    assert '!' not in tmpdir.join('test.db').read()

    assert db.contains(where('name') == 'foo')
    assert len(db) == 1


def test_encoding(tmpdir):
    japanese_doc = {"Test": u"こんにちは世界"}

    path = str(tmpdir.join('test.db'))
    # cp936 is used for japanese encodings
    jap_storage = JSONStorage(path, encoding="cp936")
    jap_storage.write(japanese_doc)

    try:
        exception = json.decoder.JSONDecodeError
    except AttributeError:
        exception = ValueError

    with pytest.raises(exception):
        # cp037 is used for english encodings
        eng_storage = JSONStorage(path, encoding="cp037")
        eng_storage.read()

    jap_storage = JSONStorage(path, encoding="cp936")
    assert japanese_doc == jap_storage.read()


def test_json_invalid_mode_warning(tmpdir):
    path = str(tmpdir.join('test.db'))
    with pytest.warns(UserWarning, match='Using an `access_mode` other than'):
        JSONStorage(path, access_mode='w')


def test_json_write_serialization_failure_preserves_data(tmpdir):
    """If json.dumps fails, the existing file data must remain intact."""
    path = str(tmpdir.join('test.db'))
    storage = JSONStorage(path)

    # Write valid data first
    original = {'key': 'original_value'}
    storage.write(original)
    assert storage.read() == original

    # Attempt to write non-serializable data — json.dumps should fail
    bad_data = {'key': object()}
    with pytest.raises(TypeError):
        storage.write(bad_data)

    # Original data must still be readable
    assert storage.read() == original
    storage.close()


def test_json_write_io_failure_preserves_data(tmpdir):
    """If the file replace step fails, existing data must not be corrupted."""
    path = str(tmpdir.join('test.db'))
    storage = JSONStorage(path)

    # Write valid data first
    original = {'key': 'original_value'}
    storage.write(original)
    assert storage.read() == original

    # Mock os.replace to simulate a failure during the atomic swap
    real_replace = os.replace
    call_count = [0]

    def failing_replace(*args, **kwargs):
        call_count[0] += 1
        raise OSError("Simulated replace failure")

    with patch('tinydb.storages.os.replace', side_effect=failing_replace):
        with pytest.raises(OSError, match="Simulated replace failure"):
            storage.write({'key': 'new_value'})

    assert call_count[0] == 1

    # After failure, the storage handle should be re-opened and the
    # original data should still be intact
    assert storage.read() == original
    storage.close()


def test_json_write_shorter_after_longer(tmpdir):
    """Writing shorter data after longer data must not leave trailing junk."""
    path = str(tmpdir.join('test.db'))
    storage = JSONStorage(path)

    # Write a long payload first
    long_data = {'key': 'x' * 10000}
    storage.write(long_data)
    assert storage.read() == long_data

    # Write a much shorter payload — old tail must not corrupt the file
    short_data = {'k': 1}
    storage.write(short_data)
    assert storage.read() == short_data

    # Verify the raw file content is valid JSON with no trailing data
    with open(path, 'r') as f:
        raw = f.read()
    assert json.loads(raw) == short_data
    storage.close()


def test_json_write_read_only_mode(tmpdir):
    """Writing in read-only mode must raise IOError without touching the file."""
    path = str(tmpdir.join('test.db'))

    # Create the database with some data
    storage = JSONStorage(path)
    storage.write({'key': 'value'})
    storage.close()

    # Re-open in read-only mode
    ro_storage = JSONStorage(path, access_mode='r')
    assert ro_storage.read() == {'key': 'value'}

    with pytest.raises(IOError, match='Cannot write'):
        ro_storage.write({'key': 'new'})

    # Original data must be unchanged
    assert ro_storage.read() == {'key': 'value'}
    ro_storage.close()
