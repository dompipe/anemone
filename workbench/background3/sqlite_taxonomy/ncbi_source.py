#!/usr/bin/env python3
"""Local NCBI Taxonomy source cache for the Anemone taxonomy builder.

The cache is deliberately separate from the 35-GiB Anemone knowledge database.
It is a staging/index database built from NCBI new_taxdump and can be deleted
and rebuilt at any time.
"""

from __future__ import annotations

import argparse
import sqlite3
import tarfile
import urllib.request
from pathlib import Path
from typing import Iterator, Sequence

HERE = Path(__file__).resolve().parent
CACHE_DIR = HERE / "cache"
ARCHIVE = CACHE_DIR / "new_taxdump.tar.gz"
SOURCE_DB = CACHE_DIR / "ncbi_taxonomy_source.sqlite3"
NCBI_URL = "https://ftp.ncbi.nlm.nih.gov/pub/taxonomy/new_taxdump/new_taxdump.tar.gz"

SOURCE_SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
PRAGMA temp_store=MEMORY;

CREATE TABLE IF NOT EXISTS SOURCE_NODE (
    tax_id     INTEGER PRIMARY KEY,
    parent_id  INTEGER NOT NULL,
    rank       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_source_node_parent ON SOURCE_NODE(parent_id);
CREATE INDEX IF NOT EXISTS idx_source_node_rank ON SOURCE_NODE(rank);

CREATE TABLE IF NOT EXISTS SOURCE_NAME (
    tax_id      INTEGER NOT NULL,
    name        TEXT NOT NULL,
    name_class  TEXT NOT NULL,
    PRIMARY KEY(tax_id, name, name_class)
);
CREATE INDEX IF NOT EXISTS idx_source_name_tax_class
ON SOURCE_NAME(tax_id, name_class);
CREATE INDEX IF NOT EXISTS idx_source_name_lower
ON SOURCE_NAME(name COLLATE NOCASE);

CREATE TABLE IF NOT EXISTS SOURCE_META (
    meta_key   TEXT PRIMARY KEY,
    meta_value TEXT NOT NULL
);
"""


def _split_dmp(line: str) -> list[str]:
    return [part.strip() for part in line.rstrip("\n").split("\t|\t")]


def download_taxdump(
    archive: Path = ARCHIVE,
    *,
    url: str = NCBI_URL,
    force: bool = False,
) -> Path:
    archive.parent.mkdir(parents=True, exist_ok=True)
    if archive.exists() and archive.stat().st_size > 0 and not force:
        return archive
    tmp = archive.with_suffix(archive.suffix + ".part")
    with urllib.request.urlopen(url, timeout=120) as response, tmp.open("wb") as out:
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            out.write(chunk)
    tmp.replace(archive)
    return archive


def _member_lines(tf: tarfile.TarFile, name: str) -> Iterator[str]:
    member = tf.getmember(name)
    raw = tf.extractfile(member)
    if raw is None:
        raise RuntimeError(f"cannot read {name} from taxdump")
    for binary in raw:
        yield binary.decode("utf-8", errors="replace")


def build_source_db(
    archive: Path = ARCHIVE,
    db_path: Path = SOURCE_DB,
    *,
    rebuild: bool = False,
    batch_size: int = 50_000,
) -> Path:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if rebuild and db_path.exists():
        db_path.unlink()
    db = sqlite3.connect(str(db_path))
    db.executescript(SOURCE_SCHEMA)

    loaded = db.execute(
        "SELECT meta_value FROM SOURCE_META WHERE meta_key='loaded'"
    ).fetchone()
    if loaded and loaded[0] == "1":
        db.close()
        return db_path

    db.execute("DELETE FROM SOURCE_NODE")
    db.execute("DELETE FROM SOURCE_NAME")

    with tarfile.open(archive, "r:gz") as tf:
        node_batch: list[tuple[int, int, str]] = []
        for line in _member_lines(tf, "nodes.dmp"):
            parts = _split_dmp(line)
            if len(parts) < 3:
                continue
            node_batch.append((int(parts[0]), int(parts[1]), parts[2].lower()))
            if len(node_batch) >= batch_size:
                db.executemany(
                    "INSERT OR REPLACE INTO SOURCE_NODE(tax_id,parent_id,rank) VALUES(?,?,?)",
                    node_batch,
                )
                node_batch.clear()
        if node_batch:
            db.executemany(
                "INSERT OR REPLACE INTO SOURCE_NODE(tax_id,parent_id,rank) VALUES(?,?,?)",
                node_batch,
            )
        db.commit()

        name_batch: list[tuple[int, str, str]] = []
        for line in _member_lines(tf, "names.dmp"):
            parts = _split_dmp(line)
            if len(parts) < 4:
                continue
            tax_id = int(parts[0])
            name = parts[1]
            name_class = parts[3].rstrip("\t|").strip().lower()
            if not name:
                continue
            name_batch.append((tax_id, name, name_class))
            if len(name_batch) >= batch_size:
                db.executemany(
                    "INSERT OR IGNORE INTO SOURCE_NAME(tax_id,name,name_class) VALUES(?,?,?)",
                    name_batch,
                )
                name_batch.clear()
        if name_batch:
            db.executemany(
                "INSERT OR IGNORE INTO SOURCE_NAME(tax_id,name,name_class) VALUES(?,?,?)",
                name_batch,
            )

    db.execute(
        """INSERT INTO SOURCE_META(meta_key,meta_value) VALUES('loaded','1')
           ON CONFLICT(meta_key) DO UPDATE SET meta_value='1'"""
    )
    db.execute(
        """INSERT INTO SOURCE_META(meta_key,meta_value) VALUES('source_url',?)
           ON CONFLICT(meta_key) DO UPDATE SET meta_value=excluded.meta_value""",
        (NCBI_URL,),
    )
    db.commit()
    db.execute("PRAGMA optimize")
    db.close()
    return db_path


class NCBISource:
    def __init__(self, db_path: Path = SOURCE_DB):
        self.db_path = Path(db_path)
        self.db = sqlite3.connect(str(self.db_path))
        self.db.row_factory = sqlite3.Row

    def close(self) -> None:
        self.db.close()

    def scientific_name(self, tax_id: int) -> str | None:
        row = self.db.execute(
            """SELECT name FROM SOURCE_NAME
               WHERE tax_id=? AND name_class='scientific name'
               LIMIT 1""",
            (tax_id,),
        ).fetchone()
        return str(row[0]) if row else None

    def preferred_common_name(self, tax_id: int) -> str | None:
        row = self.db.execute(
            """SELECT name FROM SOURCE_NAME
               WHERE tax_id=? AND name_class IN (
                   'genbank common name','common name','blast name'
               )
               ORDER BY CASE name_class
                   WHEN 'genbank common name' THEN 0
                   WHEN 'common name' THEN 1
                   ELSE 2 END, length(name)
               LIMIT 1""",
            (tax_id,),
        ).fetchone()
        return str(row[0]) if row else None

    def node(self, tax_id: int) -> dict | None:
        row = self.db.execute(
            "SELECT tax_id,parent_id,rank FROM SOURCE_NODE WHERE tax_id=?",
            (tax_id,),
        ).fetchone()
        if not row:
            return None
        return {
            "tax_id": int(row["tax_id"]),
            "parent_id": int(row["parent_id"]),
            "rank": str(row["rank"]),
            "scientific_name": self.scientific_name(int(row["tax_id"])),
            "common_name": self.preferred_common_name(int(row["tax_id"])),
        }

    def kingdoms(self, limit: int | None = None) -> list[dict]:
        sql = """
            SELECT n.tax_id, sn.name AS scientific_name
            FROM SOURCE_NODE n
            JOIN SOURCE_NAME sn
              ON sn.tax_id=n.tax_id AND sn.name_class='scientific name'
            WHERE n.rank='kingdom'
            ORDER BY sn.name COLLATE NOCASE
        """
        params: tuple = ()
        if limit is not None:
            sql += " LIMIT ?"
            params = (limit,)
        rows = self.db.execute(sql, params).fetchall()
        return [
            {
                "tax_id": int(r["tax_id"]),
                "rank": "kingdom",
                "scientific_name": str(r["scientific_name"]),
                "common_name": self.preferred_common_name(int(r["tax_id"])),
            }
            for r in rows
        ]

    def nearest_descendants(
        self,
        parent_tax_id: int,
        target_ranks: Sequence[str],
        *,
        limit: int = 25,
    ) -> list[dict]:
        """Return nearest descendants whose source rank matches target_ranks.

        Traversal stops beneath a matching node, so a parent does not skip a
        nearer matching rank and return nested matches from the same branch.
        """
        ranks = tuple(r.lower() for r in target_ranks)
        placeholders = ",".join("?" for _ in ranks)
        sql = f"""
            WITH RECURSIVE walk(tax_id,parent_id,rank,depth) AS (
                SELECT n.tax_id,n.parent_id,n.rank,1
                FROM SOURCE_NODE n
                WHERE n.parent_id=?
                UNION ALL
                SELECT n.tax_id,n.parent_id,n.rank,walk.depth+1
                FROM SOURCE_NODE n
                JOIN walk ON n.parent_id=walk.tax_id
                WHERE walk.rank NOT IN ({placeholders})
            )
            SELECT w.tax_id,w.parent_id,w.rank,sn.name AS scientific_name,w.depth
            FROM walk w
            JOIN SOURCE_NAME sn
              ON sn.tax_id=w.tax_id AND sn.name_class='scientific name'
            WHERE w.rank IN ({placeholders})
            ORDER BY w.depth, sn.name COLLATE NOCASE
            LIMIT ?
        """
        params = (parent_tax_id, *ranks, *ranks, limit)
        rows = self.db.execute(sql, params).fetchall()
        return [
            {
                "tax_id": int(r["tax_id"]),
                "parent_id": int(r["parent_id"]),
                "rank": str(r["rank"]),
                "scientific_name": str(r["scientific_name"]),
                "common_name": self.preferred_common_name(int(r["tax_id"])),
                "depth": int(r["depth"]),
            }
            for r in rows
        ]

    def names(self, tax_id: int, *, limit: int = 25) -> list[dict]:
        rows = self.db.execute(
            """SELECT name,name_class FROM SOURCE_NAME
               WHERE tax_id=? AND name_class!='scientific name'
               ORDER BY
                 CASE name_class
                   WHEN 'genbank common name' THEN 0
                   WHEN 'common name' THEN 1
                   WHEN 'synonym' THEN 2
                   WHEN 'equivalent name' THEN 3
                   ELSE 9
                 END,
                 length(name), name COLLATE NOCASE
               LIMIT ?""",
            (tax_id, limit),
        ).fetchall()
        return [
            {"name": str(r["name"]), "name_class": str(r["name_class"])}
            for r in rows
        ]


def ensure_source(
    *,
    archive: Path = ARCHIVE,
    db_path: Path = SOURCE_DB,
    force_download: bool = False,
    rebuild: bool = False,
) -> Path:
    download_taxdump(archive, force=force_download)
    return build_source_db(archive, db_path, rebuild=rebuild)


def cli() -> int:
    parser = argparse.ArgumentParser(description="Build/query local NCBI taxonomy cache")
    parser.add_argument("--archive", type=Path, default=ARCHIVE)
    parser.add_argument("--db", type=Path, default=SOURCE_DB)
    sub = parser.add_subparsers(dest="command", required=True)

    p_build = sub.add_parser("build")
    p_build.add_argument("--force-download", action="store_true")
    p_build.add_argument("--rebuild", action="store_true")

    p_kingdoms = sub.add_parser("kingdoms")
    p_kingdoms.add_argument("--limit", type=int)

    args = parser.parse_args()
    if args.command == "build":
        ensure_source(
            archive=args.archive,
            db_path=args.db,
            force_download=args.force_download,
            rebuild=args.rebuild,
        )
        print(args.db)
        return 0

    if not args.db.exists():
        ensure_source(archive=args.archive, db_path=args.db)
    src = NCBISource(args.db)
    try:
        for row in src.kingdoms(limit=args.limit):
            print(f"{row['tax_id']}\t{row['scientific_name']}\t{row['common_name'] or ''}")
    finally:
        src.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(cli())
