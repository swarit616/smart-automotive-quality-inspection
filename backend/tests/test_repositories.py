import importlib.util
import unittest

from app.db import MemoryRepository
from tests.repo_contract import RepositoryContract


class MemoryRepositoryTests(RepositoryContract, unittest.TestCase):
    def setUp(self):
        self.repo = MemoryRepository()


@unittest.skipUnless(importlib.util.find_spec("sqlalchemy"), "SQLAlchemy not installed in this environment")
class SqlRepositoryTests(RepositoryContract, unittest.TestCase):
    def setUp(self):
        from app.db import make_repository

        self.repo = make_repository("sqlite://")
        self.repo.init()

    def test_schema_version_mismatch_refuses_to_start(self):
        from app.db.models import SchemaVersion

        with self.repo._Session() as s:
            s.get(SchemaVersion, 1).version = 99
            s.commit()
        with self.assertRaises(RuntimeError):
            self.repo.init()
