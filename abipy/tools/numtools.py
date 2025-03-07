# coding: utf-8
"""Numeric tools."""
from __future__ import annotations

import numpy as np
import pandas as pd

from monty.collections import dict2namedtuple
from abipy.tools import duck


def print_stats_arr(arr: np.ndarray, take_abs=False) -> None:
    """
    Print statistics on a NumPy array.

    Args:
        take_abs: use abs(arr) if True.
    """
    if np.iscomplexobj(arr):
        arr = np.abs(arr)
    if take_abs:
        arr = np.abs(arr)

    print("Mean:", np.mean(arr))
    print("Median:", np.median(arr))
    print("Standard Deviation:", np.std(arr))
    print("Variance:", np.var(arr))
    min_index = np.argmin(arr)
    print("Index of minimum value:", min_index)
    print("Minimum value:", arr[min_index])
    max_index = np.argmax(arr)
    print("Index of maximum value:", max_index)
    print("Maximum value:", arr[max_index])
    # Percentile (e.g., 25th percentile)
    print("25th Percentile:", np.percentile(arr, 25))


def nparr_to_df(name: str, arr: np.ndarrays, columns: list[str]) -> pd.DataFrame:
    """
    Insert a numpy array in a DataFrame with columns giving the indices.

    Args:
        name: Name of column with the values of the numpy array.
        arr: numpy array
        columns: List with the name of columns with the indices.
    """
    shape, ndim = arr.shape, arr.ndim
    if len(columns) != ndim:
        raise ValueError(f"{len(columns)=} != {ndim=}")

    indices = np.indices(shape).reshape(ndim, -1).T.copy()
    df = pd.DataFrame(indices, columns=columns)
    df[name] = arr.flatten()

    return df


def build_mesh(x0: float, num: int, step: float, direction: str) -> tuple[list, int]:
    """
    Generate a linear mesh of step `step` that is centered on x0 if
    directions == "centered" or a mesh that starts/ends at x0 if direction is `>`/`<`.
    Return mesh and index of x0.
    """
    if direction == "centered":
        start = x0 - num * step
        return [start + i * step for i in range(2 * num + 1)], num

    elif direction in (">", "<"):
        start, ix0 = x0, 0
        if direction == "<":
            ix0 = num - 1
            step = -abs(step)

        return sorted([start + i * step for i in range(num)]), ix0

    raise ValueError(f"Invalid {direction=}")


def transpose_last3dims(arr) -> np.ndarray:
    """
    Transpose the last three dimensions of arr: (...,x,y,z) --> (...,z,y,x).
    """
    axes = np.arange(arr.ndim)
    axes[-3:] = axes[::-1][:3]

    view = np.transpose(arr, axes=axes)
    return np.ascontiguousarray(view)


def add_periodic_replicas(arr: np.ndarray) -> np.ndarray:
    """
    Returns a new array of shape=(..., nx+1,ny+1,nz+1) with redundant data points.

    Periodicity in enforced only on the last three dimensions.
    """
    ishape, ndim = np.array(arr.shape), arr.ndim
    oshape = ishape.copy()

    if ndim == 1:
        oarr = np.empty(ishape + 1, dtype=arr.dtype)
        oarr[:-1] = arr
        oarr[-1] = arr[0]

    elif ndim == 2:
        oarr = np.empty(oshape + 1, dtype=arr.dtype)
        oarr[:-1,:-1] = arr
        oarr[-1,:-1] = arr[0,:]
        oarr[:-1,-1] = arr[:,0]
        oarr[-1,-1] = arr[0,0]

    else:
        # Add periodic replica along the last three directions.
        oshape[-3:] = oshape[-3:] + 1
        oarr = np.empty(oshape, dtype=arr.dtype)

        for x in range(ishape[-3]):
            for y in range(ishape[-2]):
                oarr[..., x, y, :-1] = arr[..., x, y, :]
                oarr[..., x, y, -1] = arr[..., x, y, 0]

            oarr[..., x, y + 1, :-1] = arr[..., x, 0, :]
            oarr[..., x, y + 1, -1] = arr[..., x, 0, 0]

        oarr[..., x + 1, :, :] = oarr[..., 0, :, :]

    return oarr


def data_from_cplx_mode(cplx_mode: str, arr, tol=None):
    """
    Extract the data from the numpy array ``arr`` depending on the values of ``cplx_mode``.

    Args:
        cplx_mode: Possible values in ("re", "im", "abs", "angle")
            "re" for the real part,
            "im" for the imaginary part.
            "all" for both re and im.
            "abs" means that the absolute value of the complex number is shown.
            "angle" will display the phase of the complex number in radians.
        tol: If not None, values below tol are set to zero. Cannot be used with "angle"
    """
    if cplx_mode == "re":
        val = arr.real
    elif cplx_mode == "im":
        val = arr.imag
    elif cplx_mode == "all":
        val = arr
    elif cplx_mode == "abs":
        val = np.abs(arr)
    elif cplx_mode == "angle":
        val = np.angle(arr, deg=False)
        if tol is not None:
            raise ValueError("Tol cannot be used with cplx_mode = angle")
    else:
        raise ValueError("Unsupported mode `%s`" % str(cplx_mode))

    return val if tol is None else np.where(np.abs(val) > tol, val, 0)


def is_diagonal(matrix, atol=1e-12):
    """
    Return True if matrix is diagonal.
    """
    m = matrix.copy()
    np.fill_diagonal(m, 0)

    if issubclass(matrix.dtype.type, np.integer):
        return np.all(m == 0)
    else:
        return np.all(np.abs(m) <= atol)


#########################################################################################
# Tools to facilitate iterations
#########################################################################################


def alternate(*iterables):
    """
    [a[0], b[0], ... , a[1], b[1], ..., a[n], b[n] ...]
    >>> alternate([1,4], [2,5], [3,6])
    [1, 2, 3, 4, 5, 6]
    """
    items = []
    for tup in zip(*iterables):
        items.extend([item for item in tup])
    return items


def iflat(iterables):
    """
    Iterator over all elements of a nested iterable. It's recursive!

    >>> list(iflat([[0], [1,2, [3,4]]]))
    [0, 1, 2, 3, 4]
    """
    for item in iterables:
        if not hasattr(item, "__iter__"):
            yield item
        else:
            # iterable object.
            for it in iflat(item):
                yield it


def grouper(n, iterable, fillvalue=None):
    """
    >>> assert grouper(3, "ABCDEFG", "x") == [('A', 'B', 'C'), ('D', 'E', 'F'), ('G', 'x', 'x')]
    >>> assert grouper(3, [1, 2, 3, 4]) == [(1, 2, 3), (4, None, None)]
    """
    # https://stackoverflow.com/questions/434287/what-is-the-most-pythonic-way-to-iterate-over-a-list-in-chunks/434411#434411
    try:
        from itertools import zip_longest
    except ImportError:
        from itertools import izip_longest as zip_longest

    args = [iter(iterable)] * n
    return list(zip_longest(fillvalue=fillvalue, *args))


def sort_and_groupby(items, key=None, reverse=False, ret_lists=False):
    """
    Sort ``items`` using ``key`` function and invoke itertools.groupby to group items.
    If ret_lists is True, a tuple of lists (keys, groups) is returned else iterator.
    See itertools.groupby for further info.

    >>> sort_and_groupby([1, 2, 1], ret_lists=True)
    ([1, 2], [[1, 1], [2]])
    """
    from itertools import groupby
    if not ret_lists:
        return groupby(sorted(items, key=key, reverse=reverse), key=key)
    else:
        keys, groups = [], []
        for hvalue, grp in groupby(sorted(items, key=key, reverse=reverse), key=key):
            keys.append(hvalue)
            groups.append(list(grp))
        return keys, groups


#########################################################################################
# Sorting and ordering
#########################################################################################

def prune_ord(alist: list) -> list:
    """
    Return new list where all duplicated items in alist are removed

    1) The order of items in alist is preserved.
    2) items in alist MUST be hashable.

    Taken from http://code.activestate.com/recipes/52560/
    >>> prune_ord([1, 1, 2, 3, 3])
    [1, 2, 3]
    """
    mset = {}
    return [mset.setdefault(e, e) for e in alist if e not in mset]

#########################################################################################
# Special functions
#########################################################################################


def gaussian(x, width, center=0.0, height=None):
    """
    Returns the values of gaussian(x) where x is array-like.

    Args:
        x: Input array.
        width: Width of the gaussian.
        center: Center of the gaussian.
        height: height of the gaussian. If height is None, a normalized gaussian is returned.
    """
    x = np.asarray(x)
    if height is None: height = 1.0 / (width * np.sqrt(2 * np.pi))

    return height * np.exp(-((x - center) / width) ** 2 / 2.)


def lorentzian(x, width, center=0.0, height=None):
    """
    Returns the values of gaussian(x) where x is array-like.

    Args:
        x: Input array.
        width: Width of the Lorentzian (half-width at half-maximum)
        center: Center of the Lorentzian.
        height: height of the Lorentzian. If height is None, a normalized Lorentzian is returned.
    """
    x = np.asarray(x)
    if height is None: height = 1.0 / (width * np.pi)

    return height * width**2 / ((x - center) ** 2 + width ** 2)

#=====================================
# === Data Interpolation/Smoothing ===
#=====================================


def smooth(x, window_len=11, window='hanning'):
    """
    smooth the data using a window with requested size.

    This method is based on the convolution of a scaled window with the signal.
    The signal is prepared by introducing reflected copies of the signal
    (with the window size) in both ends so that transient parts are minimized
    in the begining and end part of the output signal.
    Taken from http://www.scipy.org/Cookbook/SignalSmooth

    Args:
        x:
            the input signal
        window_len:
            the dimension of the smoothing window. it should be an odd integer
        window:
            the type of window from 'flat', 'hanning', 'hamming', 'bartlett', 'blackman'.
            'flat' window will produce a moving average smoothing.

    Returns:
        the smoothed signal.

    example::

        t = linspace(-2,2,0.1)
        x = sin(t)+randn(len(t))*0.1
        y = smooth(x)

    see also:

    numpy.hanning, numpy.hamming, numpy.bartlett, numpy.blackman, numpy.convolve scipy.signal.lfilter

    TODO: the window parameter could be the window itself if an array instead of a string
    """
    if x.ndim != 1:
        raise ValueError("smooth only accepts 1 dimension arrays.")

    if x.size < window_len:
        raise ValueError("Input vector needs to be bigger than window size.")

    if window_len < 3:
        return x

    if window_len % 2 == 0:
        raise ValueError("window_len should be odd.")

    windows = ['flat', 'hanning', 'hamming', 'bartlett', 'blackman']

    if window not in windows:
        raise ValueError("window must be in: " + str(windows))

    s = np.r_[x[window_len - 1:0:-1], x, x[-1:-window_len:-1]]

    if window == 'flat': # moving average
        w = np.ones(window_len, 'd')
    else:
        w = eval('np.' + window + '(window_len)')

    y = np.convolve(w / w.sum(), s, mode='valid')

    s = window_len // 2
    e = s + len(x)
    return y[s:e]


def find_convindex(values, tol, min_numpts=1, mode="abs", vinf=None):
    """
    Given a list of values and a tolerance tol, returns the leftmost index for which

        abs(value[i] - vinf) < tol if mode == "abs"

    or
        abs(value[i] - vinf) / vinf < tol if mode == "rel"

    Args:
        tol: Tolerance
        min_numpts: Minimum number of points that must be converged.
        mode: "abs" for absolute convergence, "rel" for relative convergence.
        vinf: Used to specify an alternative value instead of values[-1].
            By default, vinf = values[-1]

    Return:
        -1 if convergence is not achieved else the index in values.
    """
    vinf = values[-1] if vinf is None else vinf

    if mode == "abs":
        vdiff = [abs(v - vinf) for v in values]
    elif mode == "rel":
        vdiff = [abs(v - vinf) / vinf for v in values]
    else:
        raise ValueError("Wrong mode %s" % mode)

    numpts, i = len(vdiff), -2
    if numpts > min_numpts and vdiff[-2] < tol:
        for i in range(numpts-1, -1, -1):
            if vdiff[i] > tol:
                break
        if (numpts - i - 1) < min_numpts: i = -2

    return i + 1


def find_degs_sk(enesb, atol):
    """
    Return list of lists with the indices of the degenerated bands.

    Args:
        enesb: Iterable with energies for the different bands.
            Energies are assumed to be ordered.
        atol: Absolute tolerance. Two states are degenerated if they differ by less than `atol`.

    Return:
        List of lists. The i-th item contains the indices of the degenerates states
            for the i-th degenerated set.

    :Examples:

    >>> find_degs_sk([1, 1, 2, 3.4, 3.401], atol=0.01)
    [[0, 1], [2], [3, 4]]
    """
    ndeg = 0
    degs = [[0]]
    e0 = enesb[0]
    for ib, ee in enumerate(enesb[1:]):
        ib += 1
        if abs(ee - e0) > atol:
            e0 = ee
            ndeg += 1
            degs.append([ib])
        else:
            degs[ndeg].append(ib)

    return degs


class BlochRegularGridInterpolator:
    """
    This object interpolates the periodic part of a Bloch wavefunction in real space.
    """

    def __init__(self, structure, datar, add_replicas=True, **kwargs):
        """
        Args:
            structure: :class:`Structure` object.
            datar: [ndat, nx, ny, nz] array.
            add_replicas: If True, data is padded with redundant data points.
                in order to have a periodic 3D array of shape=[ndat, nx+1, ny+1, nz+1].
            kwargs: Extra arguments are passed to RegularGridInterpolator.
        """
        self.structure = structure

        if add_replicas:
            datar = add_periodic_replicas(datar)

        self.dtype = datar.dtype
        # We want a 4d array (ndat arrays of shape (nx, ny, nz)
        nx, ny, nz = datar.shape[-3:]
        datar = np.reshape(datar, (-1,) + (nx, ny, nz))
        self.ndat = len(datar)
        x = np.linspace(0, 1, num=nx)
        y = np.linspace(0, 1, num=ny)
        z = np.linspace(0, 1, num=nz)

        # Build `ndat` interpolators. Note that RegularGridInterpolator supports
        # [nx, ny, nz, ...] arrays but then each call operates on the full set of
        # ndat components and this complicates the declation of callbacks
        # operating on a single component.
        from scipy.interpolate import RegularGridInterpolator
        self._interpolators = [None] * self.ndat
        for i in range(self.ndat):
            self._interpolators[i] = RegularGridInterpolator((x, y, z), datar[i], **kwargs)

    def eval_points(self, frac_coords, idat=None, cartesian=False, kpoint=None, **kwargs) -> np.ndarray:
        """
        Interpolate values on an arbitrary list of points.

        Args:
            frac_coords: List of points in reduced coordinates unless `cartesian`.
            idat: Index of the sub-array to interpolate. If None, all sub-arrays are interpolated.
            cartesian: True if points are in cartesian coordinates.
            kpoint: k-point in reduced coordinates. If not None, the phase-factor e^{ikr} is included.

        Return:
            [ndat, npoints] array or [1, npoints] if idat is not None
        """
        frac_coords = np.reshape(frac_coords, (-1, 3))
        if cartesian:
            red_from_cart = self.structure.lattice.inv_matrix.T
            frac_coords = [np.dot(red_from_cart, v) for v in frac_coords]

        uc_coords = np.reshape(frac_coords, (-1, 3)) % 1

        if idat is None:
            values = np.empty((self.ndat, len(uc_coords)), dtype=self.dtype)
            for idat in range(self.ndat):
                values[idat] = self._interpolators[idat](uc_coords, **kwargs)
        else:
            values = self._interpolators[idat](uc_coords, **kwargs)

        if kpoint is not None:
            if hasattr(kpoint, "frac_coords"): kpoint = kpoint.frac_coords
            kpoint = np.reshape(kpoint, (3,))
            values *= np.exp(2j * np.pi * np.dot(frac_coords, kpoint))

        return values

    def eval_line(self, point1, point2, num=200, cartesian=False, kpoint=None, **kwargs):
        """
        Interpolate values along a line.

        Args:
            point1: First point of the line. Accepts 3d vector or integer.
                The vector is in reduced coordinates unless `cartesian == True`.
                If integer, the first point of the line is given by the i-th site of the structure
                e.g. `point1=0, point2=1` gives the line passing through the first two atoms.
            point2: Second point of the line. Same API as `point1`.
            num: Number of points sampled along the line.
            cartesian: By default, `point1` and `point1` are interpreted as points in fractional
                coordinates (if not integers). Use True to pass points in cartesian coordinates.
            kpoint: k-point in reduced coordinates. If not None, the phase-factor e^{ikr} is included.

        Return: named tuple with
            site1, site2: None if the points do not represent atomic sites.
            points: Points in fractional coords.
            dist: the distance of points along the line in Ang.
            values: numpy array of shape [ndat, num] with interpolated values.
        """
        site1 = None
        if duck.is_intlike(point1):
            if point1 > len(self.structure):
                raise ValueError("point1: %s > natom: %s" % (point1, len(self.structure)))
            site1 = self.structure[point1]
            point1 = site1.coords if cartesian else site1.frac_coords

        site2 = None
        if duck.is_intlike(point2):
            if point2 > len(self.structure):
                raise ValueError("point2: %s > natom: %s" % (point2, len(self.structure)))
            site2 = self.structure[point2]
            point2 = site2.coords if cartesian else site2.frac_coords

        point1 = np.reshape(point1, (3,))
        point2 = np.reshape(point2, (3,))
        if cartesian:
            red_from_cart = self.structure.lattice.inv_matrix.T
            point1 = np.dot(red_from_cart, point1)
            point2 = np.dot(red_from_cart, point2)

        p21 = point2 - point1
        line_points = np.reshape([alpha * p21 for alpha in np.linspace(0, 1, num=num)], (-1, 3))
        dist = self.structure.lattice.norm(line_points)
        line_points += point1

        return dict2namedtuple(site1=site1, site2=site2, points=line_points, dist=dist,
                               values=self.eval_points(line_points, kpoint=kpoint, **kwargs))


class BzRegularGridInterpolator:
    """
    This object interpolates quantities defined in the BZ.
    """
    def __init__(self, structure, shifts, datak, add_replicas=True, **kwargs):
        """
        Args:
            structure: :class:`Structure` object.
            datak: [ndat, nx, ny, nz] array.
            shifts: Shifts of the mesh (only one shift is supported here)
            add_replicas: If True, data is padded with redundant data points.
                in order to have a periodic 3D array of shape=[ndat, nx+1, ny+1, nz+1].
            kwargs: Extra arguments are passed to RegularGridInterpolator e.g.: method
                The method of interpolation to perform. Supported are “linear”, “nearest”,
                    “slinear”, “cubic”, “quintic” and “pchip”.
        """
        self.structure = structure
        self.shifts = np.reshape(shifts, (-1, 3))

        if self.shifts.shape[0] != 1:
            raise ValueError(f"Multiple shifts are not supported! {self.shifts.shape[0]=}")

        if np.any(self.shifts[0] != 0):
            raise ValueError(f"Shift should be zero but got: {self.shifts=}")

        if add_replicas:
            datak = add_periodic_replicas(datak)

        self.dtype = datak.dtype
        # We want a 4d array of shape (ndat, nx, ny, nz)
        nx, ny, nz = datak.shape[-3:]
        datak = np.reshape(datak, (-1,) + (nx, ny, nz))
        self.ndat = len(datak)
        x = np.linspace(0, 1, num=nx)
        y = np.linspace(0, 1, num=ny)
        z = np.linspace(0, 1, num=nz)

        # Build `ndat` interpolators. Note that RegularGridInterpolator supports
        # [nx, ny, nz, ...] arrays but then each call operates on the full set of
        # ndat components and this complicates the declaration of callbacks operating on a single component.
        from scipy.interpolate import RegularGridInterpolator
        self._interpolators = [None] * self.ndat

        self.abs_data_min_idat = np.empty(self.ndat)
        self.abs_data_max_idat = np.empty(self.ndat)

        for idat in range(self.ndat):
            self._interpolators[idat] = RegularGridInterpolator((x, y, z), datak[idat], **kwargs)

            # Compute min and max of |f| to be used to scale markers in matplotlib plots.
            self.abs_data_min_idat[idat] = np.min(np.abs(datak[idat]))
            self.abs_data_max_idat[idat] = np.max(np.abs(datak[idat]))

    def get_max_abs_data(self, idat=None) -> tuple:
        """
        """
        if idat is None:
            return self.abs_data_max_idat.max()
        return self.abs_data_max_idat[idat]

    def eval_kpoint(self, frac_coords, cartesian=False, **kwargs) -> np.ndarray:
        """
        Interpolate values at frac_coords

        Args:
            frac_coords: reduced coordinates of the k-point unless `cartesian`.
            cartesian: True if k-point is in cartesian coordinates.

        Return:
            [ndat] array with interpolated data.
        """
        # Handle K-point object
        if hasattr(frac_coords, "frac_coords"):
            frac_coords = frac_coords.frac_coords

        if cartesian:
            red_from_cart = self.structure.reciprocal_lattice.inv_matrix.T
            frac_coords = np.dot(red_from_cart, frac_coords)

        # Remove the shift here
        frac_coords -= self.shifts[0]

        uc_coords = np.reshape(frac_coords, (3,)) % 1

        values = np.empty(self.ndat, dtype=self.dtype)
        for idat in range(self.ndat):
            values[idat] = self._interpolators[idat](uc_coords, **kwargs)

        return values


#class PolyExtrapolator:
#
#    def __init__(xs, ys):
#        self.xs = np.array(xs)
#        self.ys = np.array(ys)
#
#    def eval(self, xvals, deg):
#        p = np.poly1d(np.polyfit(self.xs, self.ys, deg))
#        return p[xvals]
#
#    def plot_ax(self, ax, kwargs**)
#        xvals = np.linspace(0, 1.1 * self.xs.max(), 100)
#
#        from abipy.tools.plotting import add_fig_kwargs, get_ax_fig_plt
#        ax, fig, plt = get_ax_fig_plt(ax=ax)
#        ax.scatter(xs, ys, marker="o")
#        yvals = self.eval(xvals, deg=1)
#        ax.plot(xvals, p[xvals], style="k--")
#        ax.grid(True)
#        ax.legend(loc="best", shadow=True, fontsize=fontsize)
#
#        return fig
