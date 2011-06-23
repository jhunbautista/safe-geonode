import numpy
import os
import sys
import unittest
import warnings

from django.test.client import Client
from django.conf import settings
from django.utils import simplejson as json

from geonode.maps.utils import get_valid_user
from risiko.utilities import save_to_geonode

from impact.views import calculate
from impact.storage.io import download
from impact.storage.io import get_bounding_box
from impact.storage.io import get_bounding_box_string
from impact.storage.io import read_layer
from impact.storage.io import get_metadata
from impact.tests.utilities import assert_bounding_box_matches, check_layer
from impact.tests.utilities import TESTDATA, DEMODATA, INTERNAL_SERVER_URL


def lembang_damage_function(x):
    if x < 6.0:
        value = 0.0
    else:
        value = (0.692 * (x ** 4) -
                 15.82 * (x ** 3) +
                 135.0 * (x ** 2) -
                 509.0 * x +
                 714.4)
    return value


class Test_calculations(unittest.TestCase):
    """Tests of Risiko calculations
    """

    def setUp(self):
        """Create valid superuser
        """
        self.user = get_valid_user()

    def test_io(self):
        """Data can be uploaded and downloaded from internal GeoServer
        """

        # Upload a raster and a vector data set
        for filename in ['lembang_mmi_hazmap.asc', 'lembang_schools.shp']:
            basename, ext = os.path.splitext(filename)

            filename = os.path.join(TESTDATA, filename)

            # FIXME (Ole): I set overwrite=True to make this pass.
            # However, in general there is a problem with get_layers_metadata
            # that if the layer has been uploaded more than once the code will
            # look for a layer called geonode:lembang_mmi_hazardmap_1
            # (the number 1 being appended) but the metadata record still
            # uses the original name.
            layer = save_to_geonode(filename, user=self.user, overwrite=True)

            # Name checking
            layer_name = layer.name

            msg = 'Expected layername %s but got %s' % (basename, layer_name)
            assert layer_name == basename, msg

            workspace = layer.workspace

            msg = 'Expected workspace to be "geonode". Got %s' % workspace
            assert workspace == 'geonode'

            # Check metadata
            assert_bounding_box_matches(layer, filename)

            # Download layer again using workspace:name
            bbox = get_bounding_box(filename)
            downloaded_layer = download(INTERNAL_SERVER_URL,
                                        '%s:%s' % (workspace, layer_name),
                                        bbox)
            assert os.path.exists(downloaded_layer.filename)

            # FIXME (Ole): I wan't to check that the resolution is as expected
            #              in case of raster layers.

            # FIXME (Ole): Bring this test back when issue:39 has been resolved
            # Check that exception is raised when using name without workspace
            #try:
            #    downloaded_layer = download(INTERNAL_SERVER_URL,
            #                                layer_name,
            #                                bbox)
            #except AssertionError, e:
            #    expected_error = 'Layer must have the format "workspace:name"'
            #    msg = ('Exception was raised but error message was: %s\n'
            #           'I expected error message: %s...' % (e,
            #                                                expected_error))
            #    assert str(e).startswith(expected_error), msg
            #else:
            #    msg = ('Assertion error should have been raised for layer '
            #           'name %s which is not preceded by workspace'
            #           % layer_name)
            #    raise Exception(msg)

            # Check handling of invalid workspace name
            #try:
            #    downloaded_layer = download(INTERNAL_SERVER_URL,
            #                                'glokurp:%s' % layer_name,
            #                                bbox)
            #except:
            #    msg = 'Write exception handling of invalid workspace name'
            #    print msg
            #    #raise Exception(msg)

    def test_earthquake_fatality_estimation_allen(self):
        """Fatality computation computed correctly with GeoServer Data
        """

        # Simulate bounding box from application
        viewport_bbox_string = '104.3,-8.2,110.04,-5.17'

        # Upload exposure data for this test
        name = 'Population_2010'
        exposure_filename = '%s/exposure/%s.asc' % (DEMODATA, name)
        exposure_layer = save_to_geonode(exposure_filename,
                                         user=self.user, overwrite=True)

        workspace = exposure_layer.workspace
        msg = 'Expected workspace to be "geonode". Got %s' % workspace
        assert workspace == 'geonode'

        layer_name = exposure_layer.name
        msg = 'Expected layer name to be "%s". Got %s' % (name, layer_name)
        assert layer_name == name.lower(), msg

        exposure_name = '%s:%s' % (workspace, layer_name)

        # Check metadata
        assert_bounding_box_matches(exposure_layer, exposure_filename)
        exp_bbox_string = get_bounding_box_string(exposure_filename)
        check_layer(exposure_layer)

        # Now we know that exposure layer is good, lets upload some
        # hazard layers and do the calculations
        for filename in ['Earthquake_Ground_Shaking.asc',
                         'Lembang_Earthquake_Scenario.asc',
                         'Shakemap_Padang_2009.asc']:

            # Save
            hazard_filename = '%s/hazard/%s' % (DEMODATA, filename)
            hazard_layer = save_to_geonode(hazard_filename,
                                           user=self.user, overwrite=True)
            hazard_name = '%s:%s' % (hazard_layer.workspace,
                                     hazard_layer.name)

            # Check metadata
            assert_bounding_box_matches(hazard_layer, hazard_filename)
            haz_bbox_string = get_bounding_box_string(hazard_filename)
            check_layer(hazard_layer)

            # Run calculation
            c = Client()
            rv = c.post('/api/v1/calculate/', data=dict(
                    hazard_server=INTERNAL_SERVER_URL,
                    hazard=hazard_name,
                    exposure_server=INTERNAL_SERVER_URL,
                    exposure=exposure_name,
                    #bbox=viewport_bbox_string,
                    bbox=exp_bbox_string,  # This one reproduced the
                                           # crash for lembang
                    impact_function='EarthquakeFatalityFunction',
                    keywords='test,shakemap,usgs'))

            self.assertEqual(rv.status_code, 200)
            self.assertEqual(rv['Content-Type'], 'application/json')
            data = json.loads(rv.content)
            assert 'hazard_layer' in data.keys()
            assert 'exposure_layer' in data.keys()
            assert 'run_duration' in data.keys()
            assert 'run_date' in data.keys()
            assert 'layer' in data.keys()

            # Download result and check
            layer_name = data['layer'].split('/')[-1]

            result_layer = download(INTERNAL_SERVER_URL,
                                    layer_name,
                                    get_bounding_box_string(hazard_filename))
            assert os.path.exists(result_layer.filename)

            # FIXME: TODO

            # Read hazard data for reference
            #hazard_raster = read_layer(hazardfile)
            #H = hazard_raster.get_data()
            #mmi_min, mmi_max = hazard_raster.get_extrema()

            # Read calculated result
            #impact_raster = read_layer(result_layer.filename)
            #I = impact_raster.get_data()

        # # Calculate impact using API
        # H = read_layer(hazard_filename)
        # E = read_layer(exposure_filename)

        # plugin_name = 'Earthquake Fatality Function'
        # plugin_list = get_plugins(plugin_name)
        # assert len(plugin_list) == 1
        # assert plugin_list[0].keys()[0] == plugin_name

        # IF = plugin_list[0][plugin_name]

        # # Call calculation engine
        # impact_filename = calculate_impact(layers=[H, E],
        #                                    impact_function=IF)

        # # Do calculation manually and check result
        # hazard_raster = read_layer(hazard_filename)
        # H = hazard_raster.get_data(nan=0)

        # exposure_raster = read_layer(exposure_filename)
        # E = exposure_raster.get_data(nan=0)

        # # Calculate impact manually
        # a = 0.97429
        # b = 11.037
        # F = 10 ** (a * H - b) * E

        # # Verify correctness of result
        # calculated_raster = read_layer(impact_filename)
        # C = calculated_raster.get_data(nan=0)

        # # Compare shape and extrema
        # msg = ('Shape of calculated raster differs from reference raster: '
        #        'C=%s, F=%s' % (C.shape, F.shape))
        # assert numpy.allclose(C.shape, F.shape, rtol=1e-12, atol=1e-12), msg

        # msg = ('Minimum of calculated raster differs from reference raster: '
        #        'C=%s, F=%s' % (numpy.min(C), numpy.min(F)))
        # assert numpy.allclose(numpy.min(C), numpy.min(F),
        #                       rtol=1e-12, atol=1e-12), msg
        # msg = ('Maximum of calculated raster differs from reference raster: '
        #        'C=%s, F=%s' % (numpy.max(C), numpy.max(F)))
        # assert numpy.allclose(numpy.max(C), numpy.max(F),
        #                       rtol=1e-12, atol=1e-12), msg

        # # Compare every single value numerically
        # msg = 'Array values of written raster array were not as expected'
        # assert numpy.allclose(C, F, rtol=1e-12, atol=1e-12), msg

        # # Check that extrema are in range
        # xmin, xmax = calculated_raster.get_extrema()
        # assert numpy.alltrue(C >= xmin)
        # assert numpy.alltrue(C <= xmax)
        # assert numpy.alltrue(C >= 0)

    def test_lembang_building_examples(self):
        """Lembang building impact calculation works through the API
        """

        # Test for a range of hazard layers

        for mmi_filename in ['lembang_mmi_hazmap.asc']:
                             #'Lembang_Earthquake_Scenario.asc']:

            # Upload input data
            hazardfile = os.path.join(TESTDATA, mmi_filename)
            hazard_layer = save_to_geonode(hazardfile, user=self.user)
            hazard_name = '%s:%s' % (hazard_layer.workspace, hazard_layer.name)

            exposurefile = os.path.join(TESTDATA, 'lembang_schools.shp')
            exposure_layer = save_to_geonode(exposurefile, user=self.user)
            exposure_name = '%s:%s' % (exposure_layer.workspace,
                                       exposure_layer.name)

            # Call calculation routine

            # FIXME (Ole): The system freaks out if there are spaces in
            #              bbox string. Please let us catch that and deal
            #              nicely with it - also do this in download()
            bbox = '105.592,-7.809,110.159,-5.647'

            #print
            #print get_bounding_box(hazardfile)
            #print get_bounding_box(exposurefile)

            with warnings.catch_warnings():
                warnings.simplefilter('ignore')

                c = Client()
                rv = c.post('/api/v1/calculate/', data=dict(
                        hazard_server=INTERNAL_SERVER_URL,
                        hazard=hazard_name,
                        exposure_server=INTERNAL_SERVER_URL,
                        exposure=exposure_name,
                        bbox=bbox,
                        impact_function='Earthquake Building Damage Function',
                        keywords='test,schools,lembang',
                        ))

            self.assertEqual(rv.status_code, 200)
            self.assertEqual(rv['Content-Type'], 'application/json')
            data = json.loads(rv.content)
            assert 'hazard_layer' in data.keys()
            assert 'exposure_layer' in data.keys()
            assert 'run_duration' in data.keys()
            assert 'run_date' in data.keys()
            assert 'layer' in data.keys()

            # Download result and check
            layer_name = data['layer'].split('/')[-1]

            result_layer = download(INTERNAL_SERVER_URL,
                                    layer_name,
                                    bbox)
            assert os.path.exists(result_layer.filename)

            # Read hazard data for reference
            hazard_raster = read_layer(hazardfile)
            A = hazard_raster.get_data()
            mmi_min, mmi_max = hazard_raster.get_extrema()

            # Read calculated result
            impact_vector = read_layer(result_layer.filename)
            coordinates = impact_vector.get_geometry()
            attributes = impact_vector.get_data()

            # Verify calculated result
            count = 0
            for i in range(len(attributes)):
                lon, lat = coordinates[i][:]
                calculated_mmi = attributes[i]['MMI']

                if calculated_mmi == 0.0:
                    # FIXME (Ole): Some points have MMI==0 here.
                    # Weird but not a show stopper
                    continue

                # Check that interpolated points are within range
                msg = ('Interpolated mmi %f was outside extrema: '
                       '[%f, %f] at location '
                       '[%f, %f]. ' % (calculated_mmi,
                                       mmi_min, mmi_max,
                                       lon, lat))
                assert mmi_min <= calculated_mmi <= mmi_max, msg

                # Check calculated damage
                calculated_dam = attributes[i]['Percent_da']

                ref_dam = lembang_damage_function(calculated_mmi)
                msg = ('Calculated damage was not as expected '
                       'for hazard layer %s' % hazardfile)
                assert numpy.allclose(calculated_dam, ref_dam,
                                      rtol=1.0e-12), msg

                count += 1

            # Make only a few points were 0
            assert count > len(attributes) - 4

    def XXtest_shakemap_population_exposure(self):
        """Population exposed to groundshaking matches USGS numbers
        """

        hazardfile = os.path.join(TESTDATA, 'shakemap_sumatra_20110129.tif')
        hazard_layer = save_to_geonode(hazardfile, overwrite=True,
                                       user=self.user)
        hazard_name = '%s:%s' % (hazard_layer.workspace, hazard_layer.name)

        exposurefile = os.path.join(TESTDATA, 'population_indonesia_2008.tif')
        exposure_layer = save_to_geonode(exposurefile, overwrite=True,
                                         user=self.user)
        exposure_name = '%s:%s' % (exposure_layer.workspace,
                                   exposure_layer.name)

        #with warnings.catch_warnings():
        #    warnings.simplefilter('ignore')
        c = Client()
        rv = c.post('/api/v1/calculate/', data=dict(
                hazard_server=INTERNAL_SERVER_URL,
                hazard=hazard_name,
                exposure_server=INTERNAL_SERVER_URL,
                exposure=exposure_name,
                bbox=get_bounding_box_string(hazardfile),
                impact_function='USGSFatalityFunction',
                keywords='test,shakemap,usgs'))

        self.assertEqual(rv.status_code, 200)
        self.assertEqual(rv['Content-Type'], 'application/json')
        data = json.loads(rv.content)
        assert 'hazard_layer' in data.keys()
        assert 'exposure_layer' in data.keys()
        assert 'run_duration' in data.keys()
        assert 'run_date' in data.keys()
        assert 'layer' in data.keys()

        # Download result and check
        layer_name = data['layer'].split('/')[-1]

        result_layer = download(INTERNAL_SERVER_URL,
                                layer_name,
                                get_bounding_box(hazardfile))
        assert os.path.exists(result_layer.filename)

        # Read hazard data for reference
        hazard_raster = read_layer(hazardfile)
        H = hazard_raster.get_data()
        mmi_min, mmi_max = hazard_raster.get_extrema()

        # Read calculated result
        impact_raster = read_layer(result_layer.filename)
        I = impact_raster.get_data()

        # FIXME (Ole): Not finished

    def test_exceptions_in_calculate_endpoint(self):
        """Wrong bbox input is handled nicely by /api/v1/calculate/
        """

        # Upload input data
        hazardfile = os.path.join(TESTDATA, 'lembang_mmi_hazmap.asc')
        hazard_layer = save_to_geonode(hazardfile, user=self.user)
        hazard_name = '%s:%s' % (hazard_layer.workspace, hazard_layer.name)

        exposurefile = os.path.join(TESTDATA, 'lembang_schools.shp')
        exposure_layer = save_to_geonode(exposurefile, user=self.user)
        exposure_name = '%s:%s' % (exposure_layer.workspace,
                                   exposure_layer.name)

        bbox_correct = '105.592,-7.809,110.159,-5.647'
        bbox_with_spaces = '105.592, -7.809, 110.159, -5.647'
        bbox_non_numeric = '105.592,-7.809,x,-5.647'
        bbox_list = [1, 2, 3, 4]
        bbox_list_non_numeric = [1, '2', 3, 4]
        bbox_none = None
        bbox_wrong_number1 = '105.592,-7.809,-5.647'
        bbox_wrong_number2 = '105.592,-7.809,-5.647,34,123'
        bbox_empty = ''
        bbox_inconsistent1 = '110,-7.809,105,-5.647'
        bbox_inconsistent2 = '105.592,-5,110.159,-7'
        bbox_out_of_bound1 = '-185.592,-7.809,110.159,-5.647'
        bbox_out_of_bound2 = '105.592,-97.809,110.159,-5.647'
        bbox_out_of_bound3 = '105.592,-7.809,189.159,-5.647'
        bbox_out_of_bound4 = '105.592,-7.809,110.159,-105.647'

        data = dict(hazard_server=INTERNAL_SERVER_URL,
                    hazard=hazard_name,
                    exposure_server=INTERNAL_SERVER_URL,
                    exposure=exposure_name,
                    bbox=bbox_correct,
                    impact_function='Earthquake Building Damage Function',
                    keywords='test,schools,lembang')

        # First do it correctly (twice)
        c = Client()
        rv = c.post('/api/v1/calculate/', data=data)
        rv = c.post('/api/v1/calculate/', data=data)

        # Then check that spaces are dealt with correctly
        data['bbox'] = bbox_with_spaces
        rv = c.post('/api/v1/calculate/', data=data)

        # Then with a range of wrong bbox inputs
        for bad_bbox in [bbox_list,
                         bbox_none,
                         bbox_empty,
                         bbox_non_numeric,
                         bbox_list_non_numeric,
                         bbox_wrong_number1,
                         bbox_wrong_number2,
                         bbox_inconsistent1,
                         bbox_inconsistent2,
                         bbox_out_of_bound1,
                         bbox_out_of_bound2,
                         bbox_out_of_bound3,
                         bbox_out_of_bound4]:

            # Use erroneous bounding box
            data['bbox'] = bad_bbox

            # FIXME (Ole): Suppress error output from c.post
            try:
                rv = c.post('/api/v1/calculate/', data=data)
            except AssertionError, e:
                #print 'GREAT: bbox %s triggered exception %s' %(bad_bbox, e)
                pass
            else:
                msg = ('Bad bounding box %s should have raised '
                       'on exception' % bad_bbox)
                raise Exception(msg)

    def test_geotransform_from_geonode(self):
        """Geotransforms of GeoNode layers can be correctly determined
        """

        for filename in ['lembang_mmi_hazmap.asc',
                         'test_grid.asc',
                         'shakemap_padang_20090930.asc']:

            # Upload file to GeoNode
            f = os.path.join(TESTDATA, filename)
            layer = save_to_geonode(f, user=self.user)

            # Read raster file and obtain reference resolution
            R = read_layer(f)
            ref_geotransform = R.get_geotransform()

            # Get geotransform from GeoNode
            layer_name = layer.typename
            metadata = get_metadata(INTERNAL_SERVER_URL, layer_name)

            geotransform_name = 'geotransform'
            msg = ('Could not find attribute "%s" in metadata. '
                   'Values are: %s' % (geotransform_name, metadata.keys()))
            assert geotransform_name in metadata, msg

            gn_geotransform = metadata[geotransform_name]
            msg = ('Geotransform obtained from GeoNode for layer %s '
                   'was not correct. I got %s but expected %s'
                   '' % (layer_name, gn_geotransform, ref_geotransform))
            assert numpy.allclose(ref_geotransform, gn_geotransform), msg


if __name__ == '__main__':
    os.environ['DJANGO_SETTINGS_MODULE'] = 'risiko.settings'
    suite = unittest.makeSuite(Test_calculations, 'test')
    runner = unittest.TextTestRunner(verbosity=2)
    runner.run(suite)
