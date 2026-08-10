from urllib.parse import quote

from src.local_library import LocalLibraryIndex


def insert_track(index, root, track_id, title, artist, album, track_number):
    album_dir = root / artist / album
    album_dir.mkdir(parents=True, exist_ok=True)
    path = album_dir / f"{track_number:02d} - {title}.flac"
    path.write_bytes(b"audio")
    with index._connect() as con:
        con.execute(
            """
            INSERT INTO local_tracks (
                id, root, path, uri, title, artist, album_artist, album,
                compilation, track_number, duration, sample_rate, bit_depth,
                channels, codec, file_size, mtime, metadata_version, scanned_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                track_id,
                str(root.resolve()),
                str(path.resolve()),
                path.resolve().as_uri(),
                title,
                artist,
                artist,
                album,
                0,
                track_number,
                240,
                44100,
                16,
                2,
                "FLAC",
                path.stat().st_size,
                1.0,
                4,
                1.0,
            ),
        )
    return path


def test_artist_detail_uses_album_and_track_artwork_with_stable_ids(tmp_path):
    root = tmp_path / "music"
    album_dir = root / "Hozier" / "Unreal Unearth Unending"
    album_dir.mkdir(parents=True)
    cover = album_dir / "cover.jpg"
    cover.write_bytes(b"\xff\xd8" + (b"artwork" * 400))

    index = LocalLibraryIndex(
        roots=[str(root)],
        db_path=str(tmp_path / "state" / "local.sqlite3"),
    )
    insert_track(
        index,
        root,
        "local:one",
        "Too Sweet",
        "Hozier",
        "Unreal Unearth Unending",
        1,
    )
    insert_track(
        index,
        root,
        "local:two",
        "Wildflower and Barley",
        "Hozier",
        "Unreal Unearth Unending",
        2,
    )

    payload = index.artist_detail("Hozier", limit=50)

    assert payload["ok"] is True
    assert payload["artist"] == "Hozier"
    assert payload["album_count"] == 1
    assert payload["track_count"] == 2
    assert len(payload["albums"]) == 1
    album = payload["albums"][0]
    assert album["artist"] == "Hozier"
    assert album["album"] == "Unreal Unearth Unending"
    assert album["track_count"] == 2
    assert album["album_id"].startswith("local-album:")
    assert album["group_id"] == album["album_id"]
    assert album["artwork_url"] == (
        "/api/local/library/artwork?p=" +
        quote(str(cover.resolve()), safe="")
    )
    expected_artwork_url = album["artwork_url"]
    assert len(payload["tracks"]) == 2
    assert all(
        track["artwork_url"] == expected_artwork_url
        for track in payload["tracks"]
    )
    assert all(
        track["cover"] == expected_artwork_url
        for track in payload["tracks"]
    )

    search_payload = index.search("Too Sweet", limit=10)
    assert search_payload["song_count"] == 1
    assert search_payload["songs"][0]["artwork_url"] == expected_artwork_url
    assert search_payload["songs"][0]["cover"] == expected_artwork_url
