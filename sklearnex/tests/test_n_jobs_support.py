# ==============================================================================
# Copyright 2023 Intel Corporation
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==============================================================================

import inspect
import logging
from io import StringIO
from multiprocessing import cpu_count

import pytest
from sklearn.base import BaseEstimator
from sklearn.datasets import make_classification

from sklearnex.dispatcher import get_patch_map
from sklearnex.svm import SVC, NuSVC

ESTIMATORS = set(
    filter(
        lambda x: inspect.isclass(x) and issubclass(x, BaseEstimator),
        [value[0][0][2] for value in get_patch_map().values()],
    )
)

X, Y = make_classification(n_samples=40, n_features=4, random_state=42)


@pytest.mark.parametrize("estimator_class", ESTIMATORS)
@pytest.mark.parametrize("n_jobs", [None, -1, 1, 2])
def test_n_jobs_support(estimator_class, n_jobs):
    def check_estimator_doc(estimator):
        if estimator.__doc__ is not None:
            assert "n_jobs" in estimator.__doc__

    def get_sklearnex_logger_stream(level="DEBUG"):
        sklex_logger = logging.getLogger("sklearnex")
        sklex_logger.setLevel(level)
        stream = StringIO()
        channel = logging.StreamHandler(stream)
        formatter = logging.Formatter("%(name)s: %(message)s")
        channel.setFormatter(formatter)
        sklex_logger.addHandler(channel)
        return stream

    def get_logs_from_stream(stream):
        return stream.getvalue().split("\n")[:-1]

    def check_n_jobs_entry_in_logs(logs, function_name, n_jobs):
        for log in logs:
            if function_name in log and "threads" in log:
                expected_n_jobs = n_jobs if n_jobs > 0 else cpu_count() + 1 + n_jobs
                logging.info(f"{function_name}: setting {expected_n_jobs} threads")
                if f"{function_name}: setting {expected_n_jobs} threads" in log:
                    return True
        # False if n_jobs is set and not found in logs
        return n_jobs is None

    def check_method(*args, method, stream):
        method(*args)
        logs = get_logs_from_stream(stream)
        assert check_n_jobs_entry_in_logs(logs, method.__name__, n_jobs)

    estimator_kwargs = {"n_jobs": n_jobs}
    if estimator_class in [SVC, NuSVC]:
        estimator_kwargs["probability"] = True
    estimator_instance = estimator_class(**estimator_kwargs)
    # check `n_jobs` parameter doc entry
    check_estimator_doc(estimator_class)
    check_estimator_doc(estimator_instance)
    # check `n_jobs` log entry for supported methods
    stream = get_sklearnex_logger_stream()
    # `fit` call is required before other methods
    check_method(X, Y, method=estimator_instance.fit, stream=stream)
    for method_name in estimator_instance._n_jobs_supported_onedal_methods:
        if method_name == "fit":
            continue
        method = getattr(estimator_instance, method_name)
        check_method(X, method=method, stream=stream)
