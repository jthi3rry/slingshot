from __future__ import unicode_literals
import unittest
from functools import wraps
import weakref
from elasticsearch import helpers
from elasticsearch.client import Elasticsearch
from elasticsearch.helpers import scan

from slingshot.indices_manager import IndicesManagerClient
from slingshot.exceptions import IndexDoesNotExist, SameIndex, IndexAlreadyExists, IndexNotManaged

DOCS = [
    {
        '_index': 'slingshot.write',
        '_id': 'employee/53',
        '_type': 'employee',
        '_source': {
            'first_name': 'John',
            'last_name': 'Doe',
        }
    },
    {
        '_index': 'slingshot.write',
        '_id': 'employee/57',
        '_type': 'employee',
        '_source': {
            'first_name': 'Jane',
            'last_name': 'Doe',
        }
    },
    {
        '_index': 'slingshot.write',
        '_id': 'organization/3',
        '_type': 'organization',
        '_source': {
            'name': 'Acme',
        }
    }
]

CONFIG = {
    'settings': {
        'number_of_shards': '1',
        'number_of_replicas': '0',
    },
    'aliases': {
        'slingshot.test_alias': {},
    },
    'mappings': {
        'employee': {
            'properties': {
                'first_name': {
                    'type': 'string'
                },
                'last_name': {
                    'type': 'string'
                }
            }
        },
        'organization': {
            'properties': {
                'name': {
                    'type': 'string'
                }
            }
        }
    }
}


def with_managed_index(index_name, config=None, docs=None):
    def wrapper(f):
        @wraps(f)
        def decorator(self, *args, **kwargs):
            self.client.indices_manager.create(index_name, body=config)
            self.client.indices.refresh(index_name)
            if docs:
                helpers.bulk(self.client, docs, stats_only=True)
                self.client.indices.refresh(index_name)
            try:
                f(self, *args, **kwargs)
            finally:
                self.client.indices.delete(index_name)
        return decorator
    return wrapper


def with_unmanaged_index(index_name, config=None, docs=None):
    def wrapper(f):
        @wraps(f)
        def decorator(self, *args, **kwargs):
            self.client.indices.create(index_name, body=config)
            self.client.indices.refresh(index_name)
            if docs:
                helpers.bulk(self.client, docs, stats_only=True)
                self.client.indices.refresh(index_name)
            try:
                f(self, *args, **kwargs)
            finally:
                self.client.indices.delete(index_name)
        return decorator
    return wrapper


class TestIndicesManagerClient(unittest.TestCase):

    def setUp(self):
        self.client = Elasticsearch()
        self.client.indices_manager = IndicesManagerClient(weakref.proxy(self.client))

    def tearDown(self):
        pass

    @with_managed_index("slingshot", CONFIG, DOCS)
    def test_real_name(self):
        real_names = self.client.indices_manager.real_names('slingshot.write')
        self.assertEqual(1, len(real_names))

        self.assertEqual([real_names[0]], self.client.indices_manager.real_names(real_names[0]))

        with self.assertRaises(IndexDoesNotExist):
            self.client.indices_manager.real_names('does_not_exist')

    @with_managed_index("slingshot", CONFIG, DOCS)
    def test_has_alias(self):
        self.assertTrue(self.client.indices_manager.has_alias('slingshot', 'slingshot.test_alias'))

    @with_managed_index("slingshot", CONFIG, DOCS)
    def test_has_read_alias(self):
        self.assertTrue(self.client.indices_manager.has_read_alias('slingshot'))

    @with_managed_index("slingshot", CONFIG, DOCS)
    def test_has_write_alias(self):
        self.assertTrue(self.client.indices_manager.has_write_alias('slingshot'))

    @with_managed_index("slingshot", CONFIG, DOCS)
    def test_add_alias(self):
        self.client.indices_manager.add_alias('slingshot', 'slingshot.added_alias')
        self.assertTrue(self.client.indices_manager.has_alias('slingshot', 'slingshot.added_alias'))

    @with_managed_index("slingshot", CONFIG, DOCS)
    def test_remove_alias(self):
        self.client.indices_manager.remove_alias('slingshot', 'slingshot.test_alias')
        self.assertFalse(self.client.indices_manager.has_alias('slingshot', 'slingshot.test_alias'))

    @with_managed_index("slingshot", CONFIG, DOCS)
    def test_rename_alias(self):
        self.client.indices_manager.rename_alias('slingshot', 'slingshot.test_alias', 'slingshot.renamed_alias')
        self.assertFalse(self.client.indices_manager.has_alias('slingshot', 'slingshot.test_alias'))
        self.assertTrue(self.client.indices_manager.has_alias('slingshot', 'slingshot.renamed_alias'))

    @with_managed_index("slingshot", CONFIG, DOCS)
    def test_move_alias(self):
        self.client.indices.create('slingshot_tmp')
        self.client.indices_manager.move_alias('slingshot', 'slingshot_tmp', 'slingshot.test_alias')
        self.assertFalse(self.client.indices_manager.has_alias('slingshot', 'slingshot.test_alias'))
        self.assertTrue(self.client.indices_manager.has_alias('slingshot_tmp', 'slingshot.test_alias'))
        self.client.indices.delete('slingshot_tmp')

    @with_managed_index("slingshot", CONFIG, DOCS)
    @with_unmanaged_index('slingshot_tmp')
    def test_swap_alias_when_alias_exists(self):
        self.client.indices_manager.swap_alias('slingshot', 'slingshot_tmp', 'slingshot.test_alias')
        self.assertFalse(self.client.indices_manager.has_alias('slingshot', 'slingshot.test_alias'))
        self.assertTrue(self.client.indices_manager.has_alias('slingshot_tmp', 'slingshot.test_alias'))

    @with_managed_index("slingshot", CONFIG, DOCS)
    @with_unmanaged_index('slingshot_tmp')
    def test_swap_alias_when_alias_does_not_exist(self):
        self.assertFalse(self.client.indices_manager.has_alias('slingshot', 'slingshot.added_alias'))
        self.client.indices_manager.swap_alias('slingshot', 'slingshot_tmp', 'slingshot.added_alias')
        self.assertTrue(self.client.indices_manager.has_alias('slingshot_tmp', 'slingshot.added_alias'))

    @with_unmanaged_index('slingshot_tmp')
    def test_copy_pre_conditions(self):
        with self.assertRaises(SameIndex):
            self.client.indices_manager.copy('slingshot_tmp', 'slingshot_tmp')
        with self.assertRaises(IndexDoesNotExist):
            self.client.indices_manager.copy('slingshot_tmp', 'slingshot')
        with self.assertRaises(IndexDoesNotExist):
            self.client.indices_manager.copy('slingshot', 'slingshot_tmp')

    @with_managed_index("slingshot", CONFIG, DOCS)
    @with_unmanaged_index('slingshot_tmp')
    def test_copy(self):
        self.client.indices_manager.copy('slingshot', 'slingshot_tmp')
        self.client.indices.refresh('slingshot_tmp')
        self.assertEqual(len(list(scan(self.client, index='slingshot'))), len(list(scan(self.client, index='slingshot_tmp'))))

    @with_managed_index("slingshot", CONFIG, DOCS)
    @with_unmanaged_index('slingshot_tmp')
    def test_copy_with_transform(self):
        def rename_name_to_legal_name(doc):
            if doc['_type'] == 'organization':
                doc['_source']['legal_name'] = doc['_source'].pop('name')
                return doc
            return None

        self.client.indices_manager.copy('slingshot', 'slingshot_tmp', transform=rename_name_to_legal_name)
        self.client.indices.refresh('slingshot_tmp')
        docs = list(scan(self.client, index='slingshot_tmp'))
        self.assertEqual(1, len(docs))
        for doc in docs:
            self.assertFalse('name' in doc['_source'])
            self.assertTrue('legal_name' in doc['_source'])

    @with_managed_index("slingshot", CONFIG, DOCS)
    @with_unmanaged_index('slingshot_tmp')
    def test_copy_with_ignore_types(self):
        self.client.indices_manager.copy('slingshot', 'slingshot_tmp', ignore_types=['employee'])
        self.client.indices.refresh('slingshot_tmp')
        docs = list(scan(self.client, index='slingshot_tmp'))
        self.assertEqual(1, len(docs))

    def test_create(self):
        try:
            self.client.indices_manager.create('slingshot')
            self.assertTrue(self.client.indices_manager.has_read_alias('slingshot'))
            self.assertTrue(self.client.indices_manager.has_write_alias('slingshot'))
            self.assertTrue(self.client.indices_manager.is_managed('slingshot'))
        finally:
            self.client.indices.delete('slingshot')

    @with_unmanaged_index("slingshot")
    def test_create_preconditions(self):
        with self.assertRaises(IndexAlreadyExists):
            self.client.indices_manager.create('slingshot')

    @with_unmanaged_index('slingshot')
    def test_manage(self):
        self.assertFalse(self.client.indices_manager.is_managed('slingshot'))
        self.client.indices_manager.manage('slingshot')
        self.assertTrue(self.client.indices_manager.is_managed('slingshot'))

    @with_managed_index("slingshot", CONFIG, DOCS)
    def test_migrate(self):
        real_names = self.client.indices_manager.real_names('slingshot')
        docs = list(scan(self.client, index='slingshot'))
        self.assertEqual(3, len(docs))
        self.client.indices_manager.migrate('slingshot', CONFIG)
        self.assertNotEqual(real_names, self.client.indices_manager.real_names('slingshot'))
        self.client.indices.refresh('slingshot')
        docs = list(scan(self.client, index='slingshot'))
        self.assertEqual(3, len(docs))
        self.client.indices.refresh('slingshot')

    @with_unmanaged_index("slingshot")
    def manage_migrate_pre_conditions(self):
        with self.assertRaises(IndexDoesNotExist):
            self.client.indices_manager.migrate('does_not_exist')
        with self.assertRaises(IndexNotManaged):
            self.client.indices_manager.migrate('slingshot')
