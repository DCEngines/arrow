# -*- coding: utf-8 -*-
# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.

from collections import OrderedDict

import pytest
import datetime
import unittest
import decimal

import numpy as np

import pandas as pd
import pandas.util.testing as tm

from pyarrow.compat import u
import pyarrow as pa

from .pandas_examples import dataframe_with_arrays, dataframe_with_lists


def _alltypes_example(size=100):
    return pd.DataFrame({
        'uint8': np.arange(size, dtype=np.uint8),
        'uint16': np.arange(size, dtype=np.uint16),
        'uint32': np.arange(size, dtype=np.uint32),
        'uint64': np.arange(size, dtype=np.uint64),
        'int8': np.arange(size, dtype=np.int16),
        'int16': np.arange(size, dtype=np.int16),
        'int32': np.arange(size, dtype=np.int32),
        'int64': np.arange(size, dtype=np.int64),
        'float32': np.arange(size, dtype=np.float32),
        'float64': np.arange(size, dtype=np.float64),
        'bool': np.random.randn(size) > 0,
        # TODO(wesm): Pandas only support ns resolution, Arrow supports s, ms,
        # us, ns
        'datetime': np.arange("2016-01-01T00:00:00.001", size,
                              dtype='datetime64[ms]'),
        'str': [str(x) for x in range(size)],
        'str_with_nulls': [None] + [str(x) for x in range(size - 2)] + [None],
        'empty_str': [''] * size
    })


class TestPandasConversion(unittest.TestCase):

    def setUp(self):
        pass

    def tearDown(self):
        pass

    def _check_pandas_roundtrip(self, df, expected=None, nthreads=1,
                                timestamps_to_ms=False, expected_schema=None,
                                check_dtype=True, schema=None,
                                check_index=False):
        table = pa.Table.from_pandas(df, timestamps_to_ms=timestamps_to_ms,
                                     schema=schema, preserve_index=check_index)
        result = table.to_pandas(nthreads=nthreads)
        if expected_schema:
            assert table.schema.equals(expected_schema)
        if expected is None:
            expected = df
        tm.assert_frame_equal(result, expected, check_dtype=check_dtype)

    def _check_array_roundtrip(self, values, expected=None, mask=None,
                               timestamps_to_ms=False, type=None):
        arr = pa.Array.from_pandas(values, timestamps_to_ms=timestamps_to_ms,
                                   mask=mask, type=type)
        result = arr.to_pandas()

        values_nulls = pd.isnull(values)
        if mask is None:
            assert arr.null_count == values_nulls.sum()
        else:
            assert arr.null_count == (mask | values_nulls).sum()

        if mask is None:
            tm.assert_series_equal(pd.Series(result), pd.Series(values),
                                   check_names=False)
        else:
            expected = pd.Series(np.ma.masked_array(values, mask=mask))
            tm.assert_series_equal(pd.Series(result), expected,
                                   check_names=False)

    def test_all_none_objects(self):
        df = pd.DataFrame({'a': [None, None, None]})
        self._check_pandas_roundtrip(df)

    def test_all_none_category(self):
        df = pd.DataFrame({'a': [None, None, None]})
        df['a'] = df['a'].astype('category')
        self._check_pandas_roundtrip(df)

    def test_float_no_nulls(self):
        data = {}
        fields = []
        dtypes = [('f4', pa.float32()), ('f8', pa.float64())]
        num_values = 100

        for numpy_dtype, arrow_dtype in dtypes:
            values = np.random.randn(num_values)
            data[numpy_dtype] = values.astype(numpy_dtype)
            fields.append(pa.field(numpy_dtype, arrow_dtype))

        df = pd.DataFrame(data)
        schema = pa.schema(fields)
        self._check_pandas_roundtrip(df, expected_schema=schema)

    def test_float_nulls(self):
        num_values = 100

        null_mask = np.random.randint(0, 10, size=num_values) < 3
        dtypes = [('f4', pa.float32()), ('f8', pa.float64())]
        names = ['f4', 'f8']
        expected_cols = []

        arrays = []
        fields = []
        for name, arrow_dtype in dtypes:
            values = np.random.randn(num_values).astype(name)

            arr = pa.Array.from_pandas(values, null_mask)
            arrays.append(arr)
            fields.append(pa.field(name, arrow_dtype))
            values[null_mask] = np.nan

            expected_cols.append(values)

        ex_frame = pd.DataFrame(dict(zip(names, expected_cols)),
                                columns=names)

        table = pa.Table.from_arrays(arrays, names)
        assert table.schema.equals(pa.schema(fields))
        result = table.to_pandas()
        tm.assert_frame_equal(result, ex_frame)

    def test_float_object_nulls(self):
        arr = np.array([None, 1.5, np.float64(3.5)] * 5, dtype=object)
        df = pd.DataFrame({'floats': arr})
        expected = pd.DataFrame({'floats': pd.to_numeric(arr)})
        field = pa.field('floats', pa.float64())
        schema = pa.schema([field])
        self._check_pandas_roundtrip(df, expected=expected,
                                     expected_schema=schema)

    def test_int_object_nulls(self):
        arr = np.array([None, 1, np.int64(3)] * 5, dtype=object)
        df = pd.DataFrame({'ints': arr})
        expected = pd.DataFrame({'ints': pd.to_numeric(arr)})
        field = pa.field('ints', pa.int64())
        schema = pa.schema([field])
        self._check_pandas_roundtrip(df, expected=expected,
                                     expected_schema=schema)

    def test_integer_no_nulls(self):
        data = OrderedDict()
        fields = []

        numpy_dtypes = [
            ('i1', pa.int8()), ('i2', pa.int16()),
            ('i4', pa.int32()), ('i8', pa.int64()),
            ('u1', pa.uint8()), ('u2', pa.uint16()),
            ('u4', pa.uint32()), ('u8', pa.uint64()),
            ('longlong', pa.int64()), ('ulonglong', pa.uint64())
        ]
        num_values = 100

        for dtype, arrow_dtype in numpy_dtypes:
            info = np.iinfo(dtype)
            values = np.random.randint(max(info.min, np.iinfo(np.int_).min),
                                       min(info.max, np.iinfo(np.int_).max),
                                       size=num_values)
            data[dtype] = values.astype(dtype)
            fields.append(pa.field(dtype, arrow_dtype))

        df = pd.DataFrame(data)
        schema = pa.schema(fields)
        self._check_pandas_roundtrip(df, expected_schema=schema)

    def test_integer_with_nulls(self):
        # pandas requires upcast to float dtype

        int_dtypes = ['i1', 'i2', 'i4', 'i8', 'u1', 'u2', 'u4', 'u8']
        num_values = 100

        null_mask = np.random.randint(0, 10, size=num_values) < 3

        expected_cols = []
        arrays = []
        for name in int_dtypes:
            values = np.random.randint(0, 100, size=num_values)

            arr = pa.Array.from_pandas(values, null_mask)
            arrays.append(arr)

            expected = values.astype('f8')
            expected[null_mask] = np.nan

            expected_cols.append(expected)

        ex_frame = pd.DataFrame(dict(zip(int_dtypes, expected_cols)),
                                columns=int_dtypes)

        table = pa.Table.from_arrays(arrays, int_dtypes)
        result = table.to_pandas()

        tm.assert_frame_equal(result, ex_frame)

    def test_boolean_no_nulls(self):
        num_values = 100

        np.random.seed(0)

        df = pd.DataFrame({'bools': np.random.randn(num_values) > 0})
        field = pa.field('bools', pa.bool_())
        schema = pa.schema([field])
        self._check_pandas_roundtrip(df, expected_schema=schema)

    def test_boolean_nulls(self):
        # pandas requires upcast to object dtype
        num_values = 100
        np.random.seed(0)

        mask = np.random.randint(0, 10, size=num_values) < 3
        values = np.random.randint(0, 10, size=num_values) < 5

        arr = pa.Array.from_pandas(values, mask)

        expected = values.astype(object)
        expected[mask] = None

        field = pa.field('bools', pa.bool_())
        schema = pa.schema([field])
        ex_frame = pd.DataFrame({'bools': expected})

        table = pa.Table.from_arrays([arr], ['bools'])
        assert table.schema.equals(schema)
        result = table.to_pandas()

        tm.assert_frame_equal(result, ex_frame)

    def test_boolean_object_nulls(self):
        arr = np.array([False, None, True] * 100, dtype=object)
        df = pd.DataFrame({'bools': arr})
        field = pa.field('bools', pa.bool_())
        schema = pa.schema([field])
        self._check_pandas_roundtrip(df, expected_schema=schema)

    def test_unicode(self):
        repeats = 1000
        values = [u'foo', None, u'bar', u'mañana', np.nan]
        df = pd.DataFrame({'strings': values * repeats})
        field = pa.field('strings', pa.string())
        schema = pa.schema([field])

        self._check_pandas_roundtrip(df, expected_schema=schema)

    def test_bytes_to_binary(self):
        values = [u('qux'), b'foo', None, 'bar', 'qux', np.nan]
        df = pd.DataFrame({'strings': values})

        table = pa.Table.from_pandas(df)
        assert table[0].type == pa.binary()

        values2 = [b'qux', b'foo', None, b'bar', b'qux', np.nan]
        expected = pd.DataFrame({'strings': values2})
        self._check_pandas_roundtrip(df, expected)

    def test_fixed_size_bytes(self):
        values = [b'foo', None, b'bar', None, None, b'hey']
        df = pd.DataFrame({'strings': values})
        schema = pa.schema([pa.field('strings', pa.binary(3))])
        table = pa.Table.from_pandas(df, schema=schema)
        assert table.schema[0].type == schema[0].type
        assert table.schema[0].name == schema[0].name
        result = table.to_pandas()
        tm.assert_frame_equal(result, df)

    def test_fixed_size_bytes_does_not_accept_varying_lengths(self):
        values = [b'foo', None, b'ba', None, None, b'hey']
        df = pd.DataFrame({'strings': values})
        schema = pa.schema([pa.field('strings', pa.binary(3))])
        with self.assertRaises(pa.ArrowInvalid):
            pa.Table.from_pandas(df, schema=schema)

    def test_timestamps_notimezone_no_nulls(self):
        df = pd.DataFrame({
            'datetime64': np.array([
                '2007-07-13T01:23:34.123',
                '2006-01-13T12:34:56.432',
                '2010-08-13T05:46:57.437'],
                dtype='datetime64[ms]')
            })
        field = pa.field('datetime64', pa.timestamp('ms'))
        schema = pa.schema([field])
        self._check_pandas_roundtrip(
            df,
            timestamps_to_ms=True,
            expected_schema=schema,
        )

        df = pd.DataFrame({
            'datetime64': np.array([
                '2007-07-13T01:23:34.123456789',
                '2006-01-13T12:34:56.432539784',
                '2010-08-13T05:46:57.437699912'],
                dtype='datetime64[ns]')
            })
        field = pa.field('datetime64', pa.timestamp('ns'))
        schema = pa.schema([field])
        self._check_pandas_roundtrip(
            df,
            timestamps_to_ms=False,
            expected_schema=schema,
        )

    def test_timestamps_notimezone_nulls(self):
        df = pd.DataFrame({
            'datetime64': np.array([
                '2007-07-13T01:23:34.123',
                None,
                '2010-08-13T05:46:57.437'],
                dtype='datetime64[ms]')
            })
        field = pa.field('datetime64', pa.timestamp('ms'))
        schema = pa.schema([field])
        self._check_pandas_roundtrip(
            df,
            timestamps_to_ms=True,
            expected_schema=schema,
        )

        df = pd.DataFrame({
            'datetime64': np.array([
                '2007-07-13T01:23:34.123456789',
                None,
                '2010-08-13T05:46:57.437699912'],
                dtype='datetime64[ns]')
            })
        field = pa.field('datetime64', pa.timestamp('ns'))
        schema = pa.schema([field])
        self._check_pandas_roundtrip(
            df,
            timestamps_to_ms=False,
            expected_schema=schema,
        )

    def test_timestamps_with_timezone(self):
        df = pd.DataFrame({
            'datetime64': np.array([
                '2007-07-13T01:23:34.123',
                '2006-01-13T12:34:56.432',
                '2010-08-13T05:46:57.437'],
                dtype='datetime64[ms]')
            })
        df['datetime64'] = (df['datetime64'].dt.tz_localize('US/Eastern')
                            .to_frame())
        self._check_pandas_roundtrip(df, timestamps_to_ms=True)

        # drop-in a null and ns instead of ms
        df = pd.DataFrame({
            'datetime64': np.array([
                '2007-07-13T01:23:34.123456789',
                None,
                '2006-01-13T12:34:56.432539784',
                '2010-08-13T05:46:57.437699912'],
                dtype='datetime64[ns]')
            })
        df['datetime64'] = (df['datetime64'].dt.tz_localize('US/Eastern')
                            .to_frame())
        self._check_pandas_roundtrip(df, timestamps_to_ms=False)

    def test_date_infer(self):
        df = pd.DataFrame({
            'date': [datetime.date(2000, 1, 1),
                     None,
                     datetime.date(1970, 1, 1),
                     datetime.date(2040, 2, 26)]})
        table = pa.Table.from_pandas(df, preserve_index=False)
        field = pa.field('date', pa.date32())
        schema = pa.schema([field])
        assert table.schema.equals(schema)
        result = table.to_pandas()
        expected = df.copy()
        expected['date'] = pd.to_datetime(df['date'])
        tm.assert_frame_equal(result, expected)

    def test_date_objects_typed(self):
        arr = np.array([
            datetime.date(2017, 4, 3),
            None,
            datetime.date(2017, 4, 4),
            datetime.date(2017, 4, 5)], dtype=object)

        arr_i4 = np.array([17259, -1, 17260, 17261], dtype='int32')
        arr_i8 = arr_i4.astype('int64') * 86400000
        mask = np.array([False, True, False, False])

        t32 = pa.date32()
        t64 = pa.date64()

        a32 = pa.Array.from_pandas(arr, type=t32)
        a64 = pa.Array.from_pandas(arr, type=t64)

        a32_expected = pa.Array.from_pandas(arr_i4, mask=mask, type=t32)
        a64_expected = pa.Array.from_pandas(arr_i8, mask=mask, type=t64)

        assert a32.equals(a32_expected)
        assert a64.equals(a64_expected)

        # Test converting back to pandas
        colnames = ['date32', 'date64']
        table = pa.Table.from_arrays([a32, a64], colnames)
        table_pandas = table.to_pandas()

        ex_values = (np.array(['2017-04-03', '2017-04-04', '2017-04-04',
                              '2017-04-05'],
                              dtype='datetime64[D]')
                     .astype('datetime64[ns]'))
        ex_values[1] = pd.NaT.value
        expected_pandas = pd.DataFrame({'date32': ex_values,
                                        'date64': ex_values},
                                       columns=colnames)
        tm.assert_frame_equal(table_pandas, expected_pandas)

    def test_dates_from_integers(self):
        t1 = pa.date32()
        t2 = pa.date64()

        arr = np.array([17259, 17260, 17261], dtype='int32')
        arr2 = arr.astype('int64') * 86400000

        a1 = pa.Array.from_pandas(arr, type=t1)
        a2 = pa.Array.from_pandas(arr2, type=t2)

        expected = datetime.date(2017, 4, 3)
        assert a1[0].as_py() == expected
        assert a2[0].as_py() == expected

    @pytest.mark.xfail(reason="not supported ATM",
                       raises=NotImplementedError)
    def test_timedelta(self):
        # TODO(jreback): Pandas only support ns resolution
        # Arrow supports ??? for resolution
        df = pd.DataFrame({
            'timedelta': np.arange(start=0, stop=3*86400000,
                                   step=86400000,
                                   dtype='timedelta64[ms]')
            })
        pa.Table.from_pandas(df)

    def test_column_of_arrays(self):
        df, schema = dataframe_with_arrays()
        self._check_pandas_roundtrip(df, schema=schema, expected_schema=schema)
        table = pa.Table.from_pandas(df, schema=schema, preserve_index=False)
        assert table.schema.equals(schema)

        for column in df.columns:
            field = schema.field_by_name(column)
            self._check_array_roundtrip(df[column], type=field.type)

    def test_column_of_lists(self):
        df, schema = dataframe_with_lists()
        self._check_pandas_roundtrip(df, schema=schema, expected_schema=schema)
        table = pa.Table.from_pandas(df, schema=schema, preserve_index=False)
        assert table.schema.equals(schema)

        for column in df.columns:
            field = schema.field_by_name(column)
            self._check_array_roundtrip(df[column], type=field.type)

    def test_threaded_conversion(self):
        df = _alltypes_example()
        self._check_pandas_roundtrip(df, nthreads=2,
                                     timestamps_to_ms=False)

    def test_category(self):
        repeats = 5
        v1 = ['foo', None, 'bar', 'qux', np.nan]
        v2 = [4, 5, 6, 7, 8]
        v3 = [b'foo', None, b'bar', b'qux', np.nan]
        df = pd.DataFrame({'cat_strings': pd.Categorical(v1 * repeats),
                           'cat_ints': pd.Categorical(v2 * repeats),
                           'cat_binary': pd.Categorical(v3 * repeats),
                           'ints': v2 * repeats,
                           'ints2': v2 * repeats,
                           'strings': v1 * repeats,
                           'strings2': v1 * repeats,
                           'strings3': v3 * repeats})
        self._check_pandas_roundtrip(df)

        arrays = [
            pd.Categorical(v1 * repeats),
            pd.Categorical(v2 * repeats),
            pd.Categorical(v3 * repeats)
        ]
        for values in arrays:
            self._check_array_roundtrip(values)

    def test_mixed_types_fails(self):
        data = pd.DataFrame({'a': ['a', 1, 2.0]})
        with self.assertRaises(pa.ArrowException):
            pa.Table.from_pandas(data)

    def test_strided_data_import(self):
        cases = []

        columns = ['a', 'b', 'c']
        N, K = 100, 3
        random_numbers = np.random.randn(N, K).copy() * 100

        numeric_dtypes = ['i1', 'i2', 'i4', 'i8', 'u1', 'u2', 'u4', 'u8',
                          'f4', 'f8']

        for type_name in numeric_dtypes:
            cases.append(random_numbers.astype(type_name))

        # strings
        cases.append(np.array([tm.rands(10) for i in range(N * K)],
                              dtype=object)
                     .reshape(N, K).copy())

        # booleans
        boolean_objects = (np.array([True, False, True] * N, dtype=object)
                           .reshape(N, K).copy())

        # add some nulls, so dtype comes back as objects
        boolean_objects[5] = None
        cases.append(boolean_objects)

        cases.append(np.arange("2016-01-01T00:00:00.001", N * K,
                               dtype='datetime64[ms]')
                     .reshape(N, K).copy())

        strided_mask = (random_numbers > 0).astype(bool)[:, 0]

        for case in cases:
            df = pd.DataFrame(case, columns=columns)
            col = df['a']

            self._check_pandas_roundtrip(df)
            self._check_array_roundtrip(col)
            self._check_array_roundtrip(col, mask=strided_mask)

    def test_decimal_32_from_pandas(self):
        expected = pd.DataFrame({
            'decimals': [
                decimal.Decimal('-1234.123'),
                decimal.Decimal('1234.439'),
            ]
        })
        converted = pa.Table.from_pandas(expected, preserve_index=False)
        field = pa.field('decimals', pa.decimal(7, 3))
        schema = pa.schema([field])
        assert converted.schema.equals(schema)

    def test_decimal_32_to_pandas(self):
        expected = pd.DataFrame({
            'decimals': [
                decimal.Decimal('-1234.123'),
                decimal.Decimal('1234.439'),
            ]
        })
        converted = pa.Table.from_pandas(expected)
        df = converted.to_pandas()
        tm.assert_frame_equal(df, expected)

    def test_decimal_64_from_pandas(self):
        expected = pd.DataFrame({
            'decimals': [
                decimal.Decimal('-129934.123331'),
                decimal.Decimal('129534.123731'),
            ]
        })
        converted = pa.Table.from_pandas(expected, preserve_index=False)
        field = pa.field('decimals', pa.decimal(12, 6))
        schema = pa.schema([field])
        assert converted.schema.equals(schema)

    def test_decimal_64_to_pandas(self):
        expected = pd.DataFrame({
            'decimals': [
                decimal.Decimal('-129934.123331'),
                decimal.Decimal('129534.123731'),
            ]
        })
        converted = pa.Table.from_pandas(expected)
        df = converted.to_pandas()
        tm.assert_frame_equal(df, expected)

    def test_decimal_128_from_pandas(self):
        expected = pd.DataFrame({
            'decimals': [
                decimal.Decimal('394092382910493.12341234678'),
                -decimal.Decimal('314292388910493.12343437128'),
            ]
        })
        converted = pa.Table.from_pandas(expected, preserve_index=False)
        field = pa.field('decimals', pa.decimal(26, 11))
        schema = pa.schema([field])
        assert converted.schema.equals(schema)

    def test_decimal_128_to_pandas(self):
        expected = pd.DataFrame({
            'decimals': [
                decimal.Decimal('394092382910493.12341234678'),
                -decimal.Decimal('314292388910493.12343437128'),
            ]
        })
        converted = pa.Table.from_pandas(expected)
        df = converted.to_pandas()
        tm.assert_frame_equal(df, expected)

    def test_all_nones(self):
        def _check_series(s):
            converted = pa.Array.from_pandas(s)
            assert isinstance(converted, pa.NullArray)
            assert len(converted) == 3
            assert converted.null_count == 3
            assert converted[0] is pa.NA

        _check_series(pd.Series([None] * 3, dtype=object))
        _check_series(pd.Series([np.nan] * 3, dtype=object))
        _check_series(pd.Series([np.sqrt(-1)] * 3, dtype=object))

    def test_multiindex_duplicate_values(self):
        num_rows = 3
        numbers = list(range(num_rows))
        index = pd.MultiIndex.from_arrays(
            [['foo', 'foo', 'bar'], numbers],
            names=['foobar', 'some_numbers'],
        )

        df = pd.DataFrame({'numbers': numbers}, index=index)

        table = pa.Table.from_pandas(df)
        result_df = table.to_pandas()
        tm.assert_frame_equal(result_df, df)

    def test_partial_schema(self):
        data = OrderedDict([
            ('a', [0, 1, 2, 3, 4]),
            ('b', np.array([-10, -5, 0, 5, 10], dtype=np.int32)),
            ('c', [-10, -5, 0, 5, 10])
        ])
        df = pd.DataFrame(data)

        partial_schema = pa.schema([
            pa.field('a', pa.int64()),
            pa.field('b', pa.int32())
        ])

        expected_schema = pa.schema([
            pa.field('a', pa.int64()),
            pa.field('b', pa.int32()),
            pa.field('c', pa.int64())
        ])

        self._check_pandas_roundtrip(df, schema=partial_schema,
                                     expected_schema=expected_schema)

    def test_structarray(self):
        ints = pa.array([None, 2, 3], type=pa.int64())
        strs = pa.array([u'a', None, u'c'], type=pa.string())
        bools = pa.array([True, False, None], type=pa.bool_())
        arr = pa.StructArray.from_arrays(
            ['ints', 'strs', 'bools'],
            [ints, strs, bools])

        expected = pd.Series([
            {'ints': None, 'strs': u'a', 'bools': True},
            {'ints': 2, 'strs': None, 'bools': False},
            {'ints': 3, 'strs': u'c', 'bools': None},
        ])

        series = pd.Series(arr.to_pandas())
        tm.assert_series_equal(series, expected)
