from elasticsearch.exceptions import ElasticsearchException, NotFoundError


class IndexDoesNotExist(NotFoundError):
    pass


class IndexAlreadyExists(ElasticsearchException):
    pass


class SameIndex(ElasticsearchException):
    pass


class IndexAlreadyManaged(ElasticsearchException):
    pass


class IndexNotManaged(ElasticsearchException):
    pass
