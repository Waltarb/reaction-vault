-- Embeddings of remote candidates, cached so "similar to my picks" re-ranking is cheap the second time.
CREATE TABLE discover_vecs (
    source    TEXT NOT NULL,
    source_id TEXT NOT NULL,
    model     TEXT NOT NULL,
    embedding BLOB NOT NULL,
    PRIMARY KEY (source, source_id, model)
);
