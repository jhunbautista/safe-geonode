"""Wrapper around SciPy interpolation.

This module takes care of differences in assumptions about axes and
ordering of dimensions between raster files and numpy arrays.
"""

import numpy
from scipy.interpolate import RectBivariateSpline
from impact.storage.vector import Vector


def raster_spline(longitudes, latitudes, values):
    """Create spline for bivariate interpolation

    Input
        longitudes: array of monotoneously increasing latitudes (west to east)
        latitudes: array of monotoneously increasing latitudes (south to north)
        values: 2d array of values defined on grid points corresponding to
                given longitudes and latitudes

    Output
        Callable object F that returns interpolated values for arbitrary
        points within the specified domain.
        F is called as F(lon, lat) where lon and lat are either
        single valued or vector valued. Values outside domain raises an
        exception. (NOT YET IMPLEMENTED)
    """

    # Input checks
    assert len(longitudes) == values.shape[1]
    assert len(latitudes) == values.shape[0]

    # Flip matrix A up-down so that scipy will interpret latitudes correctly.
    A = numpy.flipud(values)

    # Call underlying spline
    try:
        F = RectBivariateSpline(latitudes, longitudes, A)
    except:
        msg = 'Interpolation failed. Please zoom out a bit and try again'
        raise Exception(msg)

    # Return interpolator
    return Interpolator(F, longitudes, latitudes)


class Interpolator:
    """Class providing callable 2D interpolator

    To instantiate run Interpolator(F, longitudes, latitudes), where
        F is the spline e.g. generated by RectBivariateSpline
        longitudes, latitudes: Vectors of coordinates used to create F
    """

    def __init__(self, F, longitudes, latitudes):
        self.F = F
        self.minlon = longitudes[0]
        self.maxlon = longitudes[-1]
        self.minlat = latitudes[0]
        self.maxlat = latitudes[-1]

    def __call__(self, lon, lat):
        """Interpolate to specified location

        Input
            lon, lat: Location in WGS84 geographic coordinates where
                      interpolated value is sought

        Output
            interpolated value at lon, lat
        """

        msg = ('Requested interpolation longitude %f lies outside '
               'interpolator bounds [%f, %f]. '
               'Assigning NaN.' % (lon, self.minlon, self.maxlon))
        if not self.minlon <= lon <= self.maxlon:
            #print msg
            return numpy.nan

        msg = ('Requested interpolation latitude %f lies outside '
               'interpolator bounds [%f, %f]. '
               'Assigning NaN.' % (lat, self.minlat, self.maxlat))
        if not self.minlat <= lat <= self.maxlat:
            #print msg
            return numpy.nan

        return self.F(lat, lon)


def interpolate_raster_vector(R, V, name=None):
    """Interpolate from raster layer to point data

    Input
        R: Raster data set (grid)
        V: Vector data set (points)
        name: Name for new attribute.
              If None (default) the name of R is used

    Output
        I: Vector data set; points located as V with values interpolated from R

    """

    # FIXME: I think this interpolation can do grids as well if the
    #        interpolator is called with x and y being 1D arrays (axes)

    # Input checks
    assert R.is_raster
    assert V.is_vector

    # Get raster data and corresponding x and y axes

    # FIXME (Ole): Replace NODATA with 0 until we can handle proper NaNs
    A = R.get_data(nan=0.0)
    longitudes, latitudes = R.get_geometry()
    assert len(longitudes) == A.shape[1]
    assert len(latitudes) == A.shape[0]

    # Create interpolator
    f = raster_spline(longitudes, latitudes, A)

    # Get vector geometry
    coordinates = V.get_geometry()

    # Interpolate and create new attribute
    N = len(V)
    attributes = []
    if name is None:
        name = R.get_name()

    # FIXME (Ole): Profiling may suggest that his loop should be written in C
    for i in range(N):
        xi = coordinates[i, 0]   # Longitude
        eta = coordinates[i, 1]  # Latitude

        # Use layer name from raster for new attribute
        value = float(f(xi, eta))
        attributes.append({name: value})

    return Vector(data=attributes, projection=V.get_projection(),
                  geometry=coordinates)
