import datetime
import peewee

db = peewee.DatabaseProxy()


class BaseModel(peewee.Model):
    class Meta:
        database = db


class Source(BaseModel):
    """A paper source — local directory or Zotero library."""
    name = peewee.TextField()
    source_type = peewee.TextField()  # 'directory', 'zotero'
    path = peewee.TextField(default='')  # root path for directory sources


class Folder(BaseModel):
    """A folder within a source — maps to filesystem dir or Zotero collection."""
    source = peewee.ForeignKeyField(Source, backref='folders', on_delete='CASCADE')
    name = peewee.TextField()
    parent = peewee.ForeignKeyField('self', null=True, backref='children', on_delete='CASCADE')
    path = peewee.TextField(default='')  # full path for directory folders
    zotero_key = peewee.TextField(default='')  # Zotero collection key


class Paper(BaseModel):
    title = peewee.TextField(default='')
    year = peewee.IntegerField(null=True)
    journal = peewee.TextField(default='')
    doi = peewee.TextField(default='')
    folder = peewee.ForeignKeyField(Folder, null=True, backref='papers', on_delete='SET NULL')
    zotero_key = peewee.TextField(default='')  # Zotero parent item key
    created_at = peewee.DateTimeField(default=datetime.datetime.now)


class Author(BaseModel):
    paper = peewee.ForeignKeyField(Paper, backref='authors_list', on_delete='CASCADE')
    name = peewee.TextField()
    order = peewee.IntegerField(default=0)


class PaperFile(BaseModel):
    paper = peewee.ForeignKeyField(Paper, backref='files', on_delete='CASCADE')
    path = peewee.TextField()
    hash = peewee.TextField(default='')
    status = peewee.TextField(default='pending')  # pending, processed, failed
    zotero_key = peewee.TextField(default='')  # Zotero attachment key


class Passage(BaseModel):
    paper = peewee.ForeignKeyField(Paper, backref='passages', on_delete='CASCADE')
    page = peewee.IntegerField()
    text = peewee.TextField()
