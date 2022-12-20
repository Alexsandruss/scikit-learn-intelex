#!/usr/bin/env python
#===============================================================================
# Copyright 2021 Intel Corporation
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
#===============================================================================

from sklearn.base import BaseEstimator
from sklearn.utils.extmath import fast_logdet

from scipy.sparse import issparse
import numpy as np

from onedal.datatypes import _check_array

from .._device_offload import dispatch, wrap_output_data
from sklearn.utils.validation import _deprecate_positional_args, check_is_fitted

try:
    from packaging.version import Version
except ImportError:
    from distutils.version import LooseVersion as Version

from onedal.decomposition import PCA as onedal_PCA
from sklearn.decomposition import PCA as sklearn_PCA


class PCA(sklearn_PCA):
    #@_deprecate_positional_args
    def __init__(
        self,
        n_components=None,
        *,
        copy=True,
        whiten=False,
        svd_solver="auto",
        tol=0.0,
        iterated_power="auto",
        n_oversamples=10,
        power_iteration_normalizer="auto",
        random_state=None,
    ):
        self.n_components = n_components
        self.copy = copy
        self.whiten = whiten
        self.svd_solver = svd_solver
        self.tol = tol
        self.iterated_power = iterated_power
        self.n_oversamples = n_oversamples
        self.power_iteration_normalizer = power_iteration_normalizer
        self.random_state = random_state

    def fit(self, X, y=None):
        #In sklearn here we have check_scalar call
        self._fit(X)
        return self

    def _fit(self, X):
        if issparse(X):
            raise TypeError(
                "PCA does not support sparse input. See "
                "TruncatedSVD for a possible alternative."
            )

        X = _check_array(
            X, dtype=[np.float64, np.float32], ensure_2d=True, copy=self.copy
        )

        if self.n_components is None:
            if self.svd_solver != "arpack":
                n_components = min(X.shape)
            else:
                n_components = min(X.shape) - 1
        else:
            n_components = self.n_components

        # Handle svd_solver
        self._fit_svd_solver = self.svd_solver
        #TODO: Look at parameters sets conditions at daal4py interface
        if self._fit_svd_solver == "auto":
            # Small problem or n_components == 'mle', just call full PCA
            if max(X.shape) <= 500 or n_components == "mle":
                self._fit_svd_solver = "full"
            elif n_components >= 1 and n_components < 0.8 * min(X.shape):
                self._fit_svd_solver = "randomized"
            # This is also the case of n_components in (0,1)
            else:
                self._fit_svd_solver = "full"

        # Call different fits for either full or truncated SVD
        if self._fit_svd_solver == "full":
            return dispatch(self, 'decomposition.PCA.fit', {
                'onedal': self.__class__._onedal_fit,
                'sklearn': sklearn_PCA._fit_full,
            }, X)
        elif self._fit_svd_solver == "cov":
            return dispatch(self, 'decomposition.PCA.fit', {
                'onedal': self.__class__._onedal_fit,
            }, X)
        elif self._fit_svd_solver in ["arpack", "randomized"]:
            #return self._fit_truncated(X, n_components, self._fit_svd_solver)
            return sklearn_PCA._fit_truncated(X, n_components, self._fit_svd_solver)
        else:
            raise ValueError(
                "Unrecognized svd_solver='{0}'".format(self._fit_svd_solver)
            )

    def _onedal_gpu_supported(self, method_name, *data):
        print("call _onedall_gpu_supported")
        if method_name == 'decomposition.PCA.fit':
            return self._fit_svd_solver == 'cov'
        elif method_name == 'decomposition.PCA.transform':
            return hasattr(self, '_onedal_estimator')
        raise RuntimeError(f'Unknown method {method_name} in {self.__class__.__name__}')

    def _onedal_cpu_supported(self, method_name, *data):
        if method_name == 'decomposition.PCA.fit':
            return self._fit_svd_solver in ['cov', 'full']
        elif method_name == 'decomposition.PCA.transform':
            return hasattr(self, '_onedal_estimator')
        raise RuntimeError(f'Unknown method {method_name} in {self.__class__.__name__}')

    def _onedal_fit(self, X, y=None, queue=None):
        if self.svd_solver == "full":
            method = "svd"
        elif self.svd_solver == "cov":
            method = "cov"
        else:
            raise ValueError(
                "Unknown method='{0}'".format(self.svd_solver)
            )
        onedal_params = {
            'n_components': self.n_components,
            'is_deterministic': True,
            'method': method,
            'copy': self.copy
        }
        self._onedal_estimator = onedal_PCA(**onedal_params)
        self._onedal_estimator.fit(X, y, queue=queue)
        self._save_attributes()
        #TODO: Check U value
        U = None
        S = self.singular_values_
        V = self.components_

        return U, S, V

    def _onedal_predict(self, X, queue=None):
        return self._onedal_estimator.predict(X, queue)

    def get_precision(self):
        n_features = self.components_.shape[1]

        # handle corner cases first
        if self.n_components_ == 0:
            return np.eye(n_features) / self.noise_variance_

        if np.isclose(self.noise_variance_, 0.0, atol=0.0):
            return np.linalg.inv(self.get_covariance())

        # Get precision using matrix inversion lemma
        components_ = self.components_
        exp_var = self.explained_variance_
        if self.whiten:
            components_ = components_ * np.sqrt(exp_var[:, np.newaxis])
        exp_var_diff = np.maximum(exp_var - self.noise_variance_, 0.0)
        precision = np.dot(components_, components_.T) / self.noise_variance_
        precision.flat[:: len(precision) + 1] += 1.0 / exp_var_diff
        precision = np.dot(components_.T, np.dot(np.linalg.inv(precision), components_))
        precision /= -(self.noise_variance_**2)
        precision.flat[:: len(precision) + 1] += 1.0 / self.noise_variance_
        return precision

    def transform(self, X):
        check_is_fitted(self)
        X = _check_array(
            X, dtype=[np.float64, np.float32], ensure_2d=True, copy=self.copy
        )
        return dispatch(self, 'decomposition.PCA.transform', {
            'onedal': self.__class__._onedal_predict,
            'sklearn': sklearn_PCA.transform,
        }, X)

    def _save_attributes(self):
        self.components_ = self._onedal_estimator.components_
        self.explained_variance_ = self._onedal_estimator.explained_variance_
        self.explained_variance_ratio_ = self._onedal_estimator.explained_variance_ratio_
        self.singular_values_ = self._onedal_estimator.singular_values_
        self.mean_ = self._onedal_estimator.mean_
        self.n_components_ = self._onedal_estimator.n_components_
        self.n_features_ = self._onedal_estimator.n_features_
        self.n_samples_ = self._onedal_estimator.n_samples_
        self.noise_variance_ = self._onedal_estimator.noise_variance_
        self.n_features_in_ = self._onedal_estimator.n_features_in_
        self.feature_names_in_ = self._onedal_estimator.feature_names_in_
