#! /usr/bin/env python
#===============================================================================
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
#===============================================================================
from daal4py.sklearn._utils import sklearn_check_version


if sklearn_check_version('1.2'):
    print('scipy==1.9')
elif sklearn_check_version('1.1'):
    print('scipy==1.8')
elif sklearn_check_version('1.0'):
    print('scipy==1.7')
elif sklearn_check_version('0.24'):
    print('scipy==1.6')
else:
    print('scipy')