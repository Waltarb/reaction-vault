def build_filters(
    *,
    kind: str | None = None,
    favorite: bool | None = None,
    unsorted: bool | None = None,
    collection: int | None = None,
    tag: str | None = None,
    max_bytes: int | None = None,
    transparent: bool | None = None,
) -> tuple[list[str], list]:
    """WHERE fragments over `items i`. `kind` may be 'animated' (animated or video) or 'static'."""
    where = ["i.deleted_at IS NULL"]
    params: list = []
    if kind == "animated":
        where.append("i.kind IN ('animated', 'video')")
    elif kind == "static":
        where.append("i.kind = 'image'")
    elif kind in ("image", "video"):
        where.append("i.kind = ?")
        params.append(kind)
    if favorite:
        where.append("i.favorite = 1")
    if unsorted:
        where.append(
            "NOT EXISTS (SELECT 1 FROM collection_items ci JOIN collections c ON c.id = ci.collection_id "
            "WHERE ci.item_id = i.id AND c.deleted_at IS NULL)"
        )
    if collection is not None:
        where.append("EXISTS (SELECT 1 FROM collection_items ci WHERE ci.item_id = i.id AND ci.collection_id = ?)")
        params.append(collection)
    if tag:
        where.append(
            "EXISTS (SELECT 1 FROM item_tags it JOIN tags t ON t.id = it.tag_id "
            "WHERE it.item_id = i.id AND t.name = ?)"
        )
        params.append(tag.strip().lower())
    if max_bytes is not None:
        where.append("i.bytes <= ?")
        params.append(max_bytes)
    if transparent:
        where.append("i.has_alpha = 1")
    return where, params
