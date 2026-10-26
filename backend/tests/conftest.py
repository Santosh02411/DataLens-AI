import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.profiling import build_schema


@pytest.fixture
def sales_df() -> pd.DataFrame:
    df = pd.DataFrame(
        {
            "order_id": [f"O-{i}" for i in range(1, 25)],
            "order_date": pd.to_datetime(
                ["2025-04-05", "2025-04-20", "2025-05-02", "2025-05-18", "2025-06-01", "2025-06-15"] * 2
                + ["2025-07-03", "2025-07-19", "2025-08-08", "2025-08-21", "2025-09-02", "2025-09-25"] * 2
            ),
            "region": (["West"] * 6 + ["East"] * 6) * 2,
            "revenue": [100.0] * 6 + [50.0] * 6 + [40.0] * 6 + [60.0] * 5 + [None],
            "units": list(range(1, 25)),
            "rating": [5, 4, 4, 3, 5, 4, 3, 2, 3, 4, 2, 3] * 2,
        }
    )
    return df


@pytest.fixture
def sales_schema(sales_df):
    return build_schema(sales_df)


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(Settings(llm_provider=None)))
