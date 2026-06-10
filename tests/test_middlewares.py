import os
from unittest.mock import MagicMock, patch

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


def test_caching_close_on_flush_failure():
    """close() must call storage.close() even when flush() raises."""

    class FailingStorage(MemoryStorage):
        def __init__(self):
            super().__init__()
            self.closed = False

        def write(self, data):
            raise IOError("Simulated write failure")

        def close(self):
            self.closed = True

    storage = CachingMiddleware(FailingStorage)()
    storage.write(doc)

    # close() should propagate the flush exception but still close storage
    with pytest.raises(IOError, match="Simulated write failure"):
        storage.close()

    # The underlying storage must have been closed
    assert storage.storage.closed


def test_caching_flush_retry_after_failure():
    """After a transient flush failure, retrying should succeed and write
    the correct data without double-counting."""

    class TransientFailStorage(MemoryStorage):
        def __init__(self):
            super().__init__()
            self.fail_count = 0
            self.write_count = 0

        def write(self, data):
            self.write_count += 1
            if self.fail_count > 0:
                self.fail_count -= 1
                raise IOError("Transient failure")
            self.memory = data

    storage = CachingMiddleware(TransientFailStorage)()
    storage.storage.fail_count = 1  # Fail the next write

    # Queue up a write
    storage.write(doc)
    assert storage._cache_modified_count == 1

    # First flush should fail but keep the counter intact
    with pytest.raises(IOError, match="Transient failure"):
        storage.flush()

    # Counter must still be 1 — not reset, not double-counted
    assert storage._cache_modified_count == 1

    # Retry flush should succeed
    storage.flush()
    assert storage._cache_modified_count == 0
    assert storage.storage.memory == doc

    # The underlying storage.write was called exactly twice (1 fail + 1 success)
    assert storage.storage.write_count == 2


def test_caching_flush_no_double_count_on_retry():
    """Multiple write() calls followed by a failed flush should not
    inflate the counter on retry."""

    class FailOnceStorage(MemoryStorage):
        def __init__(self):
            super().__init__()
            self.should_fail = False

        def write(self, data):
            if self.should_fail:
                raise IOError("fail")
            self.memory = data

    storage = CachingMiddleware(FailOnceStorage)()
    storage.WRITE_CACHE_SIZE = 1000  # Prevent auto-flush

    # Accumulate 5 writes in cache
    for _ in range(5):
        storage.write(doc)
    assert storage._cache_modified_count == 5

    # Fail the first flush
    storage.storage.should_fail = True
    with pytest.raises(IOError):
        storage.flush()

    # Counter must still be 5
    assert storage._cache_modified_count == 5

    # Succeed on retry
    storage.storage.should_fail = False
    storage.flush()
    assert storage._cache_modified_count == 0
    assert storage.storage.memory == doc
