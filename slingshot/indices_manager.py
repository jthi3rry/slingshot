import json
import time
import six
from copy import deepcopy
from elasticsearch import helpers
from elasticsearch.client.utils import NamespacedClient, query_params

from .exceptions import IndexDoesNotExist, IndexAlreadyExists, SameIndex, IndexAlreadyManaged
from slingshot.exceptions import IndexNotManaged


class IndicesManagerClient(NamespacedClient):

    def _read_alias(self, index):
        return index

    def _write_alias(self, index):
        return "{}.write".format(index)

    def real_names(self, alias):
        names = list(self.client.indices.get_aliases(alias).keys())
        if not names:
            raise IndexDoesNotExist("alias or index '{}' doesn't exist".format(alias))
        return names

    def has_alias(self, index, alias):
        return self.client.indices.exists_alias(name=alias, index=index)

    def has_read_alias(self, index):
        return self.has_alias(index, self._read_alias(index))

    def has_write_alias(self, index):
        return self.has_alias(index, self._write_alias(index))

    def add_alias(self, target_index, alias):
        actions = {"actions": [
            {"add": {"index": target_index, "alias": alias}}
        ]}
        return self.client.indices.update_aliases(actions)

    def remove_alias(self, target_index, alias):
        actions = {"actions": [
            {"remove": {"index": target_index, "alias": alias}}
        ]}
        return self.client.indices.update_aliases(actions)

    def rename_alias(self, target_index, source_alias, target_alias):
        actions = {"actions": [
            {"remove": {"index": target_index, "alias": source_alias}},
            {"add": {"index": target_index, "alias": target_alias}}
        ]}
        return self.client.indices.update_aliases(actions)

    def move_alias(self, source_index, target_index, alias):
        actions = {"actions": [
            {"remove": {"index": source_index, "alias": alias}},
            {"add": {"index": target_index, "alias": alias}}
        ]}
        return self.client.indices.update_aliases(actions)

    def swap_alias(self, source_index, target_index, alias):
        if not self.has_alias(source_index, alias):
            return self.add_alias(target_index, alias)
        else:
            return self.move_alias(source_index, target_index, alias)

    def copy(self, source_index, target_index, transform=None, ignore_types=None, scan_kwargs={}, bulk_kwargs={'chunk_size': 1000}, parallel=False):
        if source_index == target_index:
            raise SameIndex("source_index and target_index must be different")

        if not self.client.indices.exists(source_index):
            raise IndexDoesNotExist("source_index '{}' does not exist".format(source_index))

        if not self.client.indices.exists(target_index):
            raise IndexDoesNotExist("target_index '{}' does not exist".format(source_index))

        transform = transform or (lambda doc: doc)
        ignore_types = ignore_types or []
        hits = helpers.scan(self.client, index=source_index, fields=('_source', '_parent', '_routing', '_timestamp'), **scan_kwargs)

        def _process_hits(hits, index):
            for doc in hits:
                if doc['_type'] in ignore_types:
                    continue
                doc['_index'] = index
                doc['_op_type'] = 'create'
                if 'fields' in doc:
                    doc.update(doc.pop('fields'))
                doc = transform(doc)
                if doc is None:
                    # drop doc
                    continue
                yield doc

        # Make sure percolators are copied across too
        helpers.reindex(self.client, source_index=source_index, target_index=target_index, scan_kwargs={"doc_type": ".percolator"})
        if parallel:
            for _ in helpers.parallel_bulk(self.client, _process_hits(hits, target_index), **bulk_kwargs):
                pass
        else:
            helpers.bulk(self.client, _process_hits(hits, target_index), stats_only=True, **bulk_kwargs)

    def _generate_name(self, name):
        return ".".join([name, str(int(time.time() * 1000))])

    def is_managed(self, index):
        return self.has_write_alias(index)

    @query_params('timeout', 'master_timeout')
    def create(self, index, body=None, params=None):
        if self.client.indices.exists(index):
            raise IndexAlreadyExists("index '{}' already exists".format(index))

        config = deepcopy(body) if isinstance(body, dict) else json.loads(body) if isinstance(body, six.string_types) else {}
        aliases = {self._read_alias(index): {}, self._write_alias(index): {},}
        if 'aliases' in config:
            config['aliases'].update(aliases)
        else:
            config.update({'aliases': aliases})

        return self.client.indices.create(self._generate_name(index), body=json.dumps(config), params=params)

    def manage(self, index):
        if not self.client.indices.exists(index):
            raise IndexDoesNotExist("index '{}' does not exist".format(index))

        if self.is_managed(index):
            raise IndexAlreadyManaged("index '{}' is already managed".format(index))

        self.add_alias(index, self._write_alias(index))

    def migrate(self, index, body=None, transform=None, ignore_types=None, keep_source=False):
        if not self.client.indices.exists(index):
            raise IndexDoesNotExist("index '{}' does not exist".format(index))

        if not self.is_managed(index):
            raise IndexNotManaged("index '{}' is not managed, call manage first".format(index))

        source_index = ','.join(self.real_names(index))
        target_index = self._generate_name(index)
        target_body = deepcopy(body) if isinstance(body, dict) else json.loads(body) if isinstance(body, six.string_types) else None

        self.client.indices.create(target_index, target_body)
        self.client.indices.refresh(target_index)
        self.swap_alias(source_index, target_index, self._write_alias(index))
        self.copy(source_index, target_index, transform=transform, ignore_types=ignore_types)
        self.swap_alias(source_index, target_index, self._read_alias(index))
        if not keep_source:
            self.client.indices.delete(source_index)
