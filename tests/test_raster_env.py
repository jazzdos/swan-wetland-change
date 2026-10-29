import pytest

from wetland_change.raster.env import COG_ENV, cog_env, gdal_http_env


def test_gdal_http_env_values() -> None:
    env = gdal_http_env(
        timeout=30.0, connect_timeout=10.0, max_retry=3, retry_delay=2.0
    )
    assert env == {
        "GDAL_HTTP_TIMEOUT": "30",
        "GDAL_HTTP_CONNECTTIMEOUT": "10",
        "GDAL_HTTP_MAX_RETRY": "3",
        "GDAL_HTTP_RETRY_DELAY": "2",
    }


@pytest.mark.parametrize(
    "kwargs", [{"timeout": 0.5}, {"connect_timeout": 0.9}, {"retry_delay": 0}]
)
def test_gdal_http_env_rejects_sub_second(kwargs: dict[str, float]) -> None:
    with pytest.raises(ValueError):
        gdal_http_env(**kwargs)


def test_cog_env_merges_overrides() -> None:
    env = cog_env(AWS_REGION="ap-southeast-2")
    assert env["AWS_NO_SIGN_REQUEST"] == "YES"
    assert env["GDAL_DISABLE_READDIR_ON_OPEN"] == "EMPTY_DIR"
    assert env["GDAL_HTTP_TIMEOUT"] == "30"
    assert env["AWS_REGION"] == "ap-southeast-2"
    assert set(COG_ENV) <= set(env)
