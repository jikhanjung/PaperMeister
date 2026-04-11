"""Source tree loader — Zotero / Local roots with nested folders."""
from dataclasses import dataclass, field

from papermeister.models import Folder, Source


@dataclass
class FolderNode:
    id: int
    name: str
    zotero_key: str = ''
    children: list['FolderNode'] = field(default_factory=list)


@dataclass
class SourceNode:
    id: int
    name: str
    source_type: str  # 'zotero' | 'directory'
    roots: list[FolderNode] = field(default_factory=list)


def load_source_tree() -> list[SourceNode]:
    out: list[SourceNode] = []
    # Group sources by type so Zotero appears above Local.
    sources = list(Source.select().order_by(Source.source_type, Source.name))
    for src in sources:
        folders = list(
            Folder.select()
            .where(Folder.source == src)
            .order_by(Folder.name)
        )
        nodes_by_id: dict[int, FolderNode] = {
            f.id: FolderNode(id=f.id, name=f.name, zotero_key=f.zotero_key or '')
            for f in folders
        }
        roots: list[FolderNode] = []
        for f in folders:
            node = nodes_by_id[f.id]
            parent_id = f.parent_id if hasattr(f, 'parent_id') else (f.parent.id if f.parent else None)
            if parent_id and parent_id in nodes_by_id:
                nodes_by_id[parent_id].children.append(node)
            else:
                roots.append(node)
        out.append(SourceNode(
            id=src.id,
            name=src.name,
            source_type=src.source_type,
            roots=roots,
        ))
    return out
