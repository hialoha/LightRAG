from PIL import Image
import pytest

from lightrag.llm.transforms_qwen import _resize_pil_image


@pytest.mark.parametrize("size", [(1024, 4), (4, 1024), (10000, 1), (1, 10000)])
def test_thin_image_is_padded_and_original_is_unchanged(size):
    source = Image.new("RGB", size, "black")
    result = _resize_pil_image(source)
    assert source.size == size
    assert max(result.size) / min(result.size) < 200
    assert result.width <= 1920 and result.height <= 1080
    assert result.getextrema() == ((0, 255), (0, 255), (0, 255))


def test_ordinary_image_keeps_pixels():
    source = Image.new("RGB", (80, 40), (10, 20, 30))
    result = _resize_pil_image(source)
    assert result.size == source.size
    assert result.tobytes() == source.tobytes()
