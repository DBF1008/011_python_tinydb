import os

import pytest

from tinydb import TinyDB
from tinydb.middlewares import CachingMiddleware
from tinydb.storages import MemoryStorage, JSONStorage

doc = {'none': [None, None], 'int': 42, 'float': 3.1415899999999999,
       'list': ['LITE', 'RES_ACID', 'SUS_DEXT'],
       'dict': {'hp': 13, 'sp': 5},
       'bool': [True, False, True, False]}


def test_caching(storage):
    # Write contents
    storage.write(doc)

    # Verify contents
    assert doc == storage.read()


def test_caching_read():
    db = TinyDB(storage=CachingMiddleware(MemoryStorage))
    assert db.all() == []


def test_caching_write_many(storage):
    storage.WRITE_CACHE_SIZE = 3

    # Storage should be still empty
    assert storage.memory is None

    # Write contents
    for x in range(2):
        storage.write(doc)
        assert storage.memory is None  # Still cached

    storage.write(doc)

    # Verify contents: Cache should be emptied and written to storage
    assert storage.memory


def test_caching_flush(storage):
    # Write contents
    for _ in range(CachingMiddleware.WRITE_CACHE_SIZE - 1):
        storage.write(doc)

    # Not yet flushed...
    assert storage.memory is None

    storage.write(doc)

    # Verify contents: Cache should be emptied and written to storage
    assert storage.memory


def test_caching_flush_manually(storage):
    # Write contents
    storage.write(doc)

    storage.flush()

    # Verify contents: Cache should be emptied and written to storage
    assert storage.memory


def test_caching_write(storage):
    # Write contents
    storage.write(doc)

    storage.close()

    # Verify contents: Cache should be emptied and written to storage
    assert storage.storage.memory


def test_nested():
    storage = CachingMiddleware(MemoryStorage)
    storage()  # Initialization

    # Write contents
    storage.write(doc)

    # Verify contents
    assert doc == storage.read()


def test_caching_json_write(tmpdir):
    path = str(tmpdir.join('test.db'))

    with TinyDB(path, storage=CachingMiddleware(JSONStorage)) as db:
        db.insert({'key': 'value'})

    # Verify database filesize
    statinfo = os.stat(path)
    assert statinfo.st_size != 0

    # Assert JSON file has been closed
    assert db._storage._handle.closed

    del db

    # Reopen database
    with TinyDB(path, storage=CachingMiddleware(JSONStorage)) as db:
        assert db.all() == [{'key': 'value'}]


def test_caching_close_always_closes_storage():
    """close() must call storage.close() even when flush() raises."""
    middleware = CachingMiddleware(MemoryStorage)()

    middleware.write({'_default': {}})

    # Make the underlying storage.write raise
    def bad_write(data):
        raise OSError("disk full")

    middleware.storage.write = bad_write

    with pytest.raises(OSError):
        middleware.close()

    # Even though flush raised, storage.close() must have been called.
    # For MemoryStorage close() is a no-op, so verify via the handle
    # on JSONStorage instead — here we just verify no exception on
    # repeated close.
    middleware.storage.close()


def test_caching_close_closes_file_handle_on_flush_error(tmpdir):
    """With JSONStorage, the file handle must be closed even if flush fails."""
    path = str(tmpdir.join('test.db'))
    middleware = CachingMiddleware(JSONStorage)
    middleware(path)

    middleware.write({'_default': {'1': {'a': 1}}})

    # Sabotage the file handle to make flush fail
    real_write = middleware.storage._handle.write

    def bad_write(data):
        raise OSError("disk full")

    middleware.storage._handle.write = bad_write

    with pytest.raises(OSError):
        middleware.close()

    # The file handle should still be closed despite the flush failure
    assert middleware.storage._handle.closed


def test_caching_flush_retry_after_failure():
    """flush() can be retried after a transient write failure."""
    middleware = CachingMiddleware(MemoryStorage)()

    data = {'_default': {'1': {'val': 42}}}
    middleware.write(data)

    call_count = 0
    original_write = middleware.storage.write

    def flaky_write(d):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise OSError("transient error")
        original_write(d)

    middleware.storage.write = flaky_write

    # First flush fails
    with pytest.raises(OSError):
        middleware.flush()

    # Counter must not have been reset — data still needs flushing
    assert middleware._cache_modified_count > 0

    # Second flush succeeds
    middleware.flush()
    assert middleware._cache_modified_count == 0
    assert middleware.storage.memory == data


def test_caching_flush_no_double_counting():
    """After a failed flush, additional writes must not double-count."""
    middleware = CachingMiddleware(MemoryStorage)()

    middleware.write({'_default': {'1': {'v': 1}}})
    assert middleware._cache_modified_count == 1

    # Make flush fail
    def bad_write(d):
        raise OSError("fail")

    middleware.storage.write = bad_write

    with pytest.raises(OSError):
        middleware.flush()

    # Count preserved after failure
    assert middleware._cache_modified_count == 1

    # Another write increments normally
    middleware.write({'_default': {'1': {'v': 2}}})
    assert middleware._cache_modified_count == 2
