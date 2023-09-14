#!/usr/bin/env python
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

import logging

from daal4py.sklearn._utils import daal_check_version

if daal_check_version((2023, "P", 200)):
    import numpy as np
    from scipy.sparse import issparse
    from sklearn.cluster import KMeans as sklearn_KMeans
    from sklearn.utils._openmp_helpers import _openmp_effective_n_threads
    from sklearn.utils.validation import (
        _deprecate_positional_args,
        _num_samples,
        check_is_fitted,
    )

    from daal4py.sklearn._utils import (
        run_with_n_jobs,
        sklearn_check_version,
        support_init_with_n_jobs,
    )
    from onedal.cluster import KMeans as onedal_KMeans

    from ..._device_offload import dispatch, wrap_output_data
    from ..._utils import PatchingConditionsChain
    from ._common import BaseKMeans

    class KMeans(sklearn_KMeans, BaseKMeans):
        __doc__ = sklearn_KMeans.__doc__
        n_iter_, inertia_ = None, None
        labels_, cluster_centers_ = None, None

        if sklearn_check_version("1.2"):
            _parameter_constraints: dict = {**sklearn_KMeans._parameter_constraints}

            @support_init_with_n_jobs
            @_deprecate_positional_args
            def __init__(
                self,
                n_clusters=8,
                *,
                init="k-means++",
                n_init="auto" if sklearn_check_version("1.4") else "warn",
                max_iter=300,
                tol=1e-4,
                verbose=0,
                random_state=None,
                copy_x=True,
                algorithm="lloyd",
            ):
                super().__init__(
                    n_clusters=n_clusters,
                    init=init,
                    max_iter=max_iter,
                    tol=tol,
                    n_init=n_init,
                    verbose=verbose,
                    random_state=random_state,
                    copy_x=copy_x,
                    algorithm=algorithm,
                )

        elif sklearn_check_version("1.0"):

            @support_init_with_n_jobs
            @_deprecate_positional_args
            def __init__(
                self,
                n_clusters=8,
                *,
                init="k-means++",
                n_init=10,
                max_iter=300,
                tol=1e-4,
                verbose=0,
                random_state=None,
                copy_x=True,
                algorithm="auto",
            ):
                super().__init__(
                    n_clusters=n_clusters,
                    init=init,
                    max_iter=max_iter,
                    tol=tol,
                    n_init=n_init,
                    verbose=verbose,
                    random_state=random_state,
                    copy_x=copy_x,
                    algorithm=algorithm,
                )

        else:

            @support_init_with_n_jobs
            @_deprecate_positional_args
            def __init__(
                self,
                n_clusters=8,
                *,
                init="k-means++",
                n_init=10,
                max_iter=300,
                tol=1e-4,
                precompute_distances="deprecated",
                verbose=0,
                random_state=None,
                copy_x=True,
                n_jobs="deprecated",
                algorithm="auto",
            ):
                super().__init__(
                    n_clusters=n_clusters,
                    init=init,
                    max_iter=max_iter,
                    tol=tol,
                    precompute_distances=precompute_distances,
                    n_init=n_init,
                    verbose=verbose,
                    random_state=random_state,
                    copy_x=copy_x,
                    n_jobs=n_jobs,
                    algorithm=algorithm,
                )

        def _initialize_onedal_estimator(self):
            onedal_params = {
                "n_clusters": self.n_clusters,
                "init": self.init,
                "max_iter": self.max_iter,
                "tol": self.tol,
                "n_init": self.n_init,
                "verbose": self.verbose,
                "random_state": self.random_state,
            }

            self._onedal_estimator = onedal_KMeans(**onedal_params)

        def _onedal_fit_supported(self, method_name, X, y=None, sample_weight=None):
            assert method_name == "fit"

            class_name = self.__class__.__name__
            patching_status = PatchingConditionsChain(f"sklearn.cluster.{class_name}.fit")

            sample_count = _num_samples(X)
            self._algorithm = self.algorithm
            supported_algs = ["auto", "full", "lloyd"]
            correct_count = self.n_clusters < sample_count

            patching_status.and_conditions(
                [
                    (
                        self.algorithm in supported_algs,
                        "Only lloyd algorithm is supported.",
                    ),
                    (not issparse(self.init), "Sparse init values are not supported"),
                    (correct_count, "n_clusters is smaller than number of samples"),
                    (sample_weight is None, "Sample weight is not None."),
                    (not issparse(X), "Sparse input is not supported."),
                ]
            )

            return patching_status

        def fit(self, X, y=None, sample_weight=None):
            """Compute k-means clustering.

            Parameters
            ----------
            X : array-like or sparse matrix, shape=(n_samples, n_features)
                Training instances to cluster. It must be noted that the data
                will be converted to C ordering, which will cause a memory
                copy if the given data is not C-contiguous.

            y : Ignored
                not used, present here for API consistency by convention.

            sample_weight : array-like, shape (n_samples,), optional
                The weights for each observation in X. If None, all observations
                are assigned equal weight (default: None)

            """

            if sklearn_check_version("1.0"):
                self._check_feature_names(X, reset=True)
            if sklearn_check_version("1.2"):
                self._validate_params()

            dispatch(
                self,
                "fit",
                {
                    "onedal": self.__class__._onedal_fit,
                    "sklearn": sklearn_KMeans.fit,
                },
                X,
                y,
                sample_weight,
            )

            return self

        @run_with_n_jobs
        def _onedal_fit(self, X, _, sample_weight, queue=None):
            assert sample_weight is None

            X = self._validate_data(
                X,
                accept_sparse=False,
                dtype=[np.float64, np.float32],
            )

            if sklearn_check_version("1.2"):
                self._check_params_vs_input(X)
            else:
                self._check_params(X)

            self._n_features_out = self.n_clusters
            self._n_threads = _openmp_effective_n_threads()

            self._initialize_onedal_estimator()
            self._onedal_estimator.fit(X, queue=queue)

            self._save_attributes()

        def _onedal_predict_supported(self, method_name, X):
            assert method_name == "predict"

            class_name = self.__class__.__name__
            patching_status = PatchingConditionsChain(
                f"sklearn.cluster.{class_name}.predict"
            )

            supported_algs = ["auto", "full", "lloyd"]
            dense_centers = not issparse(self.cluster_centers_)

            patching_status.and_conditions(
                [
                    (
                        self.algorithm in supported_algs,
                        "Only lloyd algorithm is supported.",
                    ),
                    (dense_centers, "Sparse clusters is not supported."),
                    (not issparse(X), "Sparse input is not supported."),
                ]
            )

            return patching_status

        @wrap_output_data
        def predict(self, X):
            """Compute k-means clustering.

            Parameters
            ----------
            X : array-like or sparse matrix, shape=(n_samples, n_features)
                Training instances to cluster. It must be noted that the data
                will be converted to C ordering, which will cause a memory
                copy if the given data is not C-contiguous.

            y : Ignored
                not used, present here for API consistency by convention.

            sample_weight : array-like, shape (n_samples,), optional
                The weights for each observation in X. If None, all observations
                are assigned equal weight (default: None)

            """

            if sklearn_check_version("1.0"):
                self._check_feature_names(X, reset=True)
            if sklearn_check_version("1.2"):
                self._validate_params()

            return dispatch(
                self,
                "predict",
                {
                    "onedal": self.__class__._onedal_predict,
                    "sklearn": sklearn_KMeans.predict,
                },
                X,
            )

        @run_with_n_jobs
        def _onedal_predict(self, X, queue=None):
            X = self._validate_data(
                X, accept_sparse=False, reset=False, dtype=[np.float64, np.float32]
            )
            if not hasattr(self, "_onedal_estimator"):
                self._initialize_onedal_estimator()
                self._onedal_estimator.cluster_centers_ = self.cluster_centers_

            return self._onedal_estimator.predict(X, queue=queue)

        def _onedal_supported(self, method_name, *data):
            if method_name == "fit":
                return self._onedal_fit_supported(method_name, *data)
            if method_name == "predict":
                return self._onedal_predict_supported(method_name, *data)
            raise RuntimeError(
                f"Unknown method {method_name} in {self.__class__.__name__}"
            )

        def _onedal_gpu_supported(self, method_name, *data):
            return self._onedal_supported(method_name, *data)

        def _onedal_cpu_supported(self, method_name, *data):
            return self._onedal_supported(method_name, *data)

        @wrap_output_data
        def fit_transform(self, X, y=None, sample_weight=None):
            """Compute clustering and transform X to cluster-distance space.

            Equivalent to fit(X).transform(X), but more efficiently implemented.

            Parameters
            ----------
            X : {array-like, sparse matrix} of shape (n_samples, n_features)
                New data to transform.

            y : Ignored
                Not used, present here for API consistency by convention.

            sample_weight : array-like of shape (n_samples,), default=None
                The weights for each observation in X. If None, all observations
                are assigned equal weight.

            Returns
            -------
            X_new : ndarray of shape (n_samples, n_clusters)
                X transformed in the new space.
            """
            return self.fit(X, sample_weight=sample_weight)._transform(X)

        @wrap_output_data
        def transform(self, X):
            """Transform X to a cluster-distance space.

            In the new space, each dimension is the distance to the cluster
            centers. Note that even if X is sparse, the array returned by
            `transform` will typically be dense.

            Parameters
            ----------
            X : {array-like, sparse matrix} of shape (n_samples, n_features)
                New data to transform.

            Returns
            -------
            X_new : ndarray of shape (n_samples, n_clusters)
                X transformed in the new space.
            """
            check_is_fitted(self)

            X = self._check_test_data(X)
            return self._transform(X)

else:
    from daal4py.sklearn.cluster import KMeans

    logging.warning(
        "Preview KMeans requires oneDAL version >= 2023.2 " "but it was not found"
    )
