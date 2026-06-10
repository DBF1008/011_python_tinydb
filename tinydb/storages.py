"""
Contains the :class:`base class <tinydb.storages.Storage>` for storages and
implementations.
"""

import json
import os
import tempfile
import warnings
from abc import ABC, abstractmethod
from typing import Any, Optional

__all__ = ('Storage', 'JSONStorage', 'MemoryStorage')


def touch(path: str, create_dirs: bool):
    """
    Create a file if it doesn't exist yet.

    :param path: The file to create.
    :param create_dirs: Whether to create all missing parent directories.
    """
    if create_dirs:
        base_dir = os.path.dirname(path)

        # Check if we need to create missing parent directories
        if not os.path.exists(base_dir):
            os.makedirs(base_dir)

    # Create the file by opening it in 'a' mode which creates the file if it
    # does not exist yet but does not modify its contents
    with open(path, 'a'):
        pass


class Storage(ABC):
    """
    The abstract base class for all Storages.

    A Storage (de)serializes the current state of the database and stores it in
    some place (memory, file on disk, ...).
    """

    # Using ABCMeta as metaclass allows instantiating only storages that have
    # implemented read and write

    @abstractmethod
    def read(self) -> Optional[dict[str, dict[str, Any]]]:
        """
        Read the current state.

        Any kind of deserialization should go here.

        Return ``None`` here to indicate that the storage is empty.
        """

        raise NotImplementedError('To be overridden!')

    @abstractmethod
    def write(self, data: dict[str, dict[str, Any]]) -> None:
        """
        Write the current state of the database to the storage.

        Any kind of serialization should go here.

        :param data: The current state of the database.
        """

        raise NotImplementedError('To be overridden!')

    def close(self) -> None:
        """
        Optional: Close open file handles, etc.
        """

        pass


class JSONStorage(Storage):
    """
    Store the data in a JSON file.
    """

    def __init__(self, path: str, create_dirs=False, encoding=None, access_mode='r+', **kwargs):
        """
        Create a new instance.

        Also creates the storage file, if it doesn't exist and the access mode
        is appropriate for writing.

        **Note:** Using an access mode other than `r` or `r+` will probably
        lead to data loss or data corruption!

        **Note:** **Never** pass untrusted or user-controlled code as ``kwargs``
        members like ``cls`` or ``default`` will be called on every write
        operation.

        :param path: Where to store the JSON data.
        :param access_mode: mode in which the file is opened (r, r+)
        :type access_mode: str
        """

        super().__init__()

        self._mode = access_mode
        self._path = path
        self._encoding = encoding
        self.kwargs = kwargs

        if access_mode not in ('r', 'rb', 'r+', 'rb+'):
            warnings.warn(
                'Using an `access_mode` other than \'r\', \'rb\', \'r+\' '
                'or \'rb+\' can cause data loss or corruption'
            )

        # Create the file if it doesn't exist and creating is allowed by the
        # access mode
        if any([character in self._mode for character in ('+', 'w', 'a')]):  # any of the writing modes
            touch(path, create_dirs=create_dirs)

        # Open the file for reading/writing
        self._handle = open(path, mode=self._mode, encoding=encoding)

    def close(self) -> None:
        self._handle.close()

    def read(self) -> Optional[dict[str, dict[str, Any]]]:
        # Get the file size by moving the cursor to the file end and reading
        # its location
        self._handle.seek(0, os.SEEK_END)
        size = self._handle.tell()

        if not size:
            # File is empty, so we return ``None`` so TinyDB can properly
            # initialize the database
            return None
        else:
            # Return the cursor to the beginning of the file
            self._handle.seek(0)

            # Load the JSON contents of the file
            return json.load(self._handle)

    def write(self, data: dict[str, dict[str, Any]]):
        # Check write permission upfront to avoid creating temp files for
        # read-only databases
        if not self._handle.writable():
            raise IOError(
                'Cannot write to the database. '
                'Access mode is "{0}"'.format(self._mode)
            )

        # Serialize FIRST — if this fails, no file I/O happens and the
        # existing file remains untouched
        serialized = json.dumps(data, **self.kwargs)

        # Write to a temporary file in the same directory, then atomically
        # replace the original file. This prevents partial-write corruption.
        dir_name = os.path.dirname(os.path.abspath(self._path))
        fd = None
        tmp_path = None
        try:
            fd, tmp_path = tempfile.mkstemp(
                dir=dir_name, suffix='.tmp'
            )
            os.write(fd, serialized.encode(self._encoding or 'utf-8'))
            os.fsync(fd)
            os.close(fd)
            fd = None  # Mark as closed so cleanup doesn't double-close

            # Close the old handle before replacing (required on Windows)
            self._handle.close()

            # Atomic replace: the old file is swapped out only once the new
            # one is fully written and synced
            os.replace(tmp_path, self._path)
            tmp_path = None  # Mark as consumed so cleanup doesn't delete it

        except BaseException:
            # Clean up the temp file if it was created but not yet replaced
            if tmp_path is not None:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
            # Close the temp fd if still open
            if fd is not None:
                try:
                    os.close(fd)
                except OSError:
                    pass
            # Re-open the original file handle if it was closed
            if self._handle.closed:
                self._handle = open(
                    self._path, mode=self._mode, encoding=self._encoding
                )
            raise

        # Re-open the handle to the (now-replaced) file for subsequent reads
        self._handle = open(
            self._path, mode=self._mode, encoding=self._encoding
        )


class MemoryStorage(Storage):
    """
    Store the data as JSON in memory.
    """

    def __init__(self):
        """
        Create a new instance.
        """

        super().__init__()
        self.memory = None

    def read(self) -> Optional[dict[str, dict[str, Any]]]:
        return self.memory

    def write(self, data: dict[str, dict[str, Any]]):
        self.memory = data
