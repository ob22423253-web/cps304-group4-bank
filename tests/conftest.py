import os, sys
import pytest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.cluster import Cluster

@pytest.fixture
def cluster():
    with Cluster() as c:
        yield c

@pytest.fixture
def teller(cluster):
    c = cluster.client("teller1")
    yield c
    c.close()
