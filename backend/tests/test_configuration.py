import pytest

from app.core.config import Settings
from app.core.exceptions import ConfigurationException


VALID_DATABASE_URL = (
    "postgresql+asyncpg://test:test@unreachable.invalid:5432/test"
)
DEFAULTED_VARIABLES = (
    "REQUEST_TIMEOUT",
    "CONTEXT_MESSAGE_LIMIT",
    "MAX_CONTEXT_TOKENS",
    "DEFAULT_SYSTEM_PROMPT",
    "CORS_ORIGINS",
    "DEEPSEEK_API_KEY",
    "DEEPSEEK_BASE_URL",
    "DEEPSEEK_MODEL",
    "EMBEDDING_MODEL",
    "RAG_VECTOR_STORE_PATH",
    "RAG_COLLECTION_NAME",
    "RAG_CHUNK_SIZE",
    "RAG_CHUNK_OVERLAP",
    "RAG_TOP_K",
)


@pytest.fixture
def valid_mock_environment(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", VALID_DATABASE_URL)
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    for name in DEFAULTED_VARIABLES:
        monkeypatch.delenv(name, raising=False)


def test_valid_mock_settings_use_canonical_rag_defaults_without_deepseek_key(
    valid_mock_environment,
):
    configured = Settings()

    assert configured.llm_provider == "mock"
    assert configured.deepseek_api_key == ""
    assert configured.database_url == VALID_DATABASE_URL
    assert configured.rag_vector_store_path == "/app/vector_data"
    assert configured.rag_collection_name == "business_knowledge"


@pytest.mark.parametrize("value", [None, "", "   "])
def test_database_url_is_required(valid_mock_environment, monkeypatch, value):
    if value is None:
        monkeypatch.delenv("DATABASE_URL")
    else:
        monkeypatch.setenv("DATABASE_URL", value)

    with pytest.raises(ConfigurationException, match="^DATABASE_URL is required$"):
        Settings()


@pytest.mark.parametrize(
    "database_url",
    [
        "not a database URL with credential-sentinel",
        "postgresql://user:credential-sentinel@localhost/database",
    ],
)
def test_database_url_must_use_valid_async_postgresql_driver_without_echoing_value(
    valid_mock_environment,
    monkeypatch,
    database_url,
):
    monkeypatch.setenv("DATABASE_URL", database_url)

    with pytest.raises(ConfigurationException) as caught:
        Settings()

    assert str(caught.value) == (
        "DATABASE_URL must be a valid postgresql+asyncpg URL"
    )
    assert "credential-sentinel" not in str(caught.value)


def test_provider_is_normalized(valid_mock_environment, monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "  MoCk  ")

    assert Settings().llm_provider == "mock"


def test_unsupported_provider_fails_at_configuration(
    valid_mock_environment,
    monkeypatch,
):
    monkeypatch.setenv("LLM_PROVIDER", "unsupported")

    with pytest.raises(
        ConfigurationException,
        match="^LLM_PROVIDER must be one of: mock, deepseek$",
    ):
        Settings()


@pytest.mark.parametrize("api_key", [None, "", "   "])
def test_deepseek_requires_non_blank_key(
    valid_mock_environment,
    monkeypatch,
    api_key,
):
    monkeypatch.setenv("LLM_PROVIDER", "deepseek")
    if api_key is None:
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    else:
        monkeypatch.setenv("DEEPSEEK_API_KEY", api_key)

    with pytest.raises(
        ConfigurationException,
        match=(
            "^DEEPSEEK_API_KEY is required when "
            "LLM_PROVIDER=deepseek$"
        ),
    ):
        Settings()


@pytest.mark.parametrize(
    ("name", "value", "message"),
    [
        ("REQUEST_TIMEOUT", "0", "REQUEST_TIMEOUT must be greater than 0"),
        ("REQUEST_TIMEOUT", "nan", "REQUEST_TIMEOUT must be greater than 0"),
        ("MAX_CONTEXT_TOKENS", "0", "MAX_CONTEXT_TOKENS must be greater than 0"),
        ("RAG_TOP_K", "0", "RAG_TOP_K must be greater than 0"),
        ("RAG_TOP_K", "not-an-int", "RAG_TOP_K must be an integer"),
        ("RAG_CHUNK_SIZE", "0", "RAG_CHUNK_SIZE must be greater than 0"),
        (
            "RAG_CHUNK_OVERLAP",
            "-1",
            "RAG_CHUNK_OVERLAP must be greater than or equal to 0",
        ),
    ],
)
def test_invalid_numeric_configuration_fails_clearly(
    valid_mock_environment,
    monkeypatch,
    name,
    value,
    message,
):
    monkeypatch.setenv(name, value)

    with pytest.raises(ConfigurationException, match=f"^{message}$"):
        Settings()


def test_rag_overlap_must_be_less_than_chunk_size(
    valid_mock_environment,
    monkeypatch,
):
    monkeypatch.setenv("RAG_CHUNK_SIZE", "100")
    monkeypatch.setenv("RAG_CHUNK_OVERLAP", "100")

    with pytest.raises(
        ConfigurationException,
        match="^RAG_CHUNK_OVERLAP must be less than RAG_CHUNK_SIZE$",
    ):
        Settings()


def test_cors_accepts_single_origin(valid_mock_environment, monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", "https://review.example:8443")

    assert Settings().cors_origins == ["https://review.example:8443"]


def test_cors_trims_multiple_origins(valid_mock_environment, monkeypatch):
    monkeypatch.setenv(
        "CORS_ORIGINS",
        " http://localhost:3000, https://review.example ",
    )

    assert Settings().cors_origins == [
        "http://localhost:3000",
        "https://review.example",
    ]


@pytest.mark.parametrize(
    "origins",
    [
        "",
        "   ",
        "http://localhost:3000,",
        "*",
        "ftp://review.example",
        "http:///missing-host",
        "http://user:password@review.example",
        "https://review.example/path",
        "https://review.example?query=yes",
        "https://review.example#fragment",
        "https://review.example:not-a-port",
    ],
)
def test_cors_rejects_empty_wildcard_or_invalid_origins(
    valid_mock_environment,
    monkeypatch,
    origins,
):
    monkeypatch.setenv("CORS_ORIGINS", origins)

    with pytest.raises(ConfigurationException, match="^CORS_ORIGINS "):
        Settings()
