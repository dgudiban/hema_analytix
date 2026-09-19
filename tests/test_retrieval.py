"""Retrieval tests: chunk loading and TF-IDF ranking over the curated KB."""
from app.services import kb_loader, retrieval_service


def test_chunks_load():
    chunks = kb_loader.load_chunks()
    by_id = {c.id: c for c in chunks}
    # 45 biomarker chunks + 6 general chunks
    assert len(chunks) == 51
    assert "kb-bio-bm001" in by_id
    assert by_id["kb-bio-bm001"].title == "Hemoglobin"
    assert by_id["kb-bio-bm001"].biomarker_id == "BM001"
    assert "kb-gen-01" in by_id
    assert all(c.text for c in chunks)


def test_retrieve_hemoglobin():
    hits = retrieval_service.retrieve("hemoglobin", top_k=3)
    assert hits
    assert hits[0].chunk.biomarker_id == "BM001"
    assert all(h.score > 0 for h in hits)


def test_retrieve_general_chunk():
    hits = retrieval_service.retrieve("how does BloodIQ classify LOW NORMAL HIGH results", top_k=3)
    assert hits
    assert hits[0].chunk.id == "kb-gen-01"


def test_retrieve_empty_query():
    assert retrieval_service.retrieve("   ") == []


def test_retrieve_top_k_respected():
    hits = retrieval_service.retrieve("cholesterol", top_k=2)
    assert len(hits) <= 2


def test_retriever_singleton_reused():
    assert retrieval_service.get_retriever() is retrieval_service.get_retriever()
