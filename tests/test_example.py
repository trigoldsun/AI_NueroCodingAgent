import pytest
from example import add

def test_add():
    """Test that add function returns correct sum."""
    assert add(2, 3) == 5

def test_add_negative():
    """Test that add function handles negative numbers."""
    assert add(-1, -1) == -2
