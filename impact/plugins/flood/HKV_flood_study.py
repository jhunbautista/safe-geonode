import numpy

from impact.plugins.core import FunctionProvider
from impact.storage.raster import Raster

# FIXME (Ole): This one works, but needs styling
class FloodImpactFunction(FunctionProvider):
    """Risk plugin for flood impact

    :author HKV
    :rating 1
    :param requires category=='hazard' and \
                    subcategory.startswith('flood') and \
                    layer_type=='raster' and \
                    unit=='m'
    :param requires category=='exposure' and \
                    subcategory.startswith('population') and \
                    layer_type=='raster' and \
                    datatype=='hkv'
    """

    @staticmethod
    def run(layers):
        """Risk plugin for earthquake fatalities

        Input
          layers: List of layers expected to contain
              H: Raster layer of flood depth
              P: Raster layer of population data on the same grid as H
        """

        threshold = 0.1  # Depth above which people are regarded affected [m]
        pixel_area = 2500  # FIXME (Ole): Get this from dataset

        # Identify hazard and exposure layers
        inundation = layers[0]  # Flood inundation [m]
        population = layers[1]  # Population density [people/100000 m^2]

        # Scale resampled population density
        # FIXME (Ole) - TODO
        current_res = population.get_resolution()[0]
        keywords = population.get_keywords()
        if 'resolution' in keywords:
            # Clunky - see issue #171
            native_res = float(keywords['resolution'])

            #print 'current res', current_res
            #print 'native res', native_res

            scaling = (current_res / native_res) ** 2
            #print 'scaling', scaling
        else:
            scaling = 1

        # Extract data as numeric arrays
        D = inundation.get_data(nan=0.0)  # Depth
        P = population.get_data(nan=0.0)  # Population density

        # Calculate impact as population exposed to depths > threshold
        I = numpy.where(D > threshold, P, 0) / 100000.0 * pixel_area

        # Generate text with result for this study
        number_of_people_affected = numpy.nansum(I.flat)
        caption = ('%i people affected by flood levels greater '
                   'than %i cm' % (number_of_people_affected,
                                   threshold * 100))

        # Create raster object and return
        R = Raster(I,
                   projection=inundation.get_projection(),
                   geotransform=inundation.get_geotransform(),
                   name='People affected',
                   keywords={'caption': caption})
        return R
