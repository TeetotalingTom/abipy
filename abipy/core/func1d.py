# coding: utf-8
"""
Function1D describes a function of a single variable and provides an easy-to-use API
for performing common tasks such as algebraic operations, integrations, differentiations, plots ...
"""
from __future__ import annotations

import numpy as np

from io import StringIO
from typing import Tuple, Union
from monty.functools import lazy_property
from abipy.tools.typing import Figure
from abipy.tools.plotting import (add_fig_kwargs, get_ax_fig_plt, add_plotly_fig_kwargs, PlotlyRowColDesc, get_fig_plotly)
from abipy.tools.derivatives import finite_diff
from abipy.tools.serialization import pmg_serialize
from abipy.tools.numtools import data_from_cplx_mode

__all__ = [
    "Function1D",
]


class Function1D:
    """
    Immutable object representing a real|complex function of real variable.
    """

    @classmethod
    def from_constant(cls, mesh, const) -> Function1D:
        """Build a constant function from the mesh and the scalar ``const``"""
        mesh = np.ascontiguousarray(mesh)
        return cls(mesh, np.ones(mesh.shape) * const)

    @classmethod
    def from_func(cls, func, mesh) -> Function1D:
        """
        Initialize the object from a callable.

        :example:

           Function1D.from_func(np.sin, mesh=np.arange(1,10))
        """
        return cls(mesh, np.vectorize(func)(mesh))

    @pmg_serialize
    def as_dict(self) -> dict:
        """Makes Function1D obey the general json interface used in pymatgen for easier serialization."""
        return {"mesh": self.mesh, "values": self.values}

    @classmethod
    def from_dict(cls, d: dict) -> Function1D:
        """
        Reconstruct object from the dictionary in MSONable format produced by as_dict.
        """
        return cls(d["mesh"], d["values"])

    @classmethod
    def from_file(cls, path, comments="#", delimiter=None, usecols=(0, 1)) -> Function1D:
        """
        Initialize an instance by reading data from path (txt format)
        see also :func:`np.loadtxt`

        Args:
            path: Path to the file containing data.
            comments: The character used to indicate the start of a comment; default: '#'.
            delimiter: str, optional The string used to separate values. By default, this is any whitespace.
            usecols: sequence, optional. Which columns to read, with 0 being the first.
                For example, usecols = (1,4) will extract data from the 2nd, and 5th columns.
        """
        mesh, values = np.loadtxt(path, comments=comments, delimiter=delimiter,
                                  usecols=usecols, unpack=True)
        return cls(mesh, values)


    def __init__(self, mesh, values):
        """
        Args:
            mesh: array-like object with the real points of the grid.
            values: array-like object with the values of the function (can be complex-valued)
        """
        mesh = np.ascontiguousarray(mesh)
        self._mesh = np.real(mesh)
        self._values = np.ascontiguousarray(values)
        assert len(self.mesh) == len(self.values)

    @property
    def mesh(self) -> np.ndarray:
        """|numpy-array| with the mesh points"""
        return self._mesh

    @property
    def values(self) -> np.ndarray:
        """Values of the functions."""
        return self._values

    def __len__(self) -> int:
        return len(self.mesh)

    def __iter__(self):
        return zip(self.mesh, self.values)

    def __getitem__(self, slice) -> Tuple[float, float]:
        return self.mesh[slice], self.values[slice]

    def __eq__(self, other) -> bool:
        if other is None: return False
        return (self.has_same_mesh(other) and
                np.allclose(self.values, other.values))

    def __ne__(self, other) -> bool:
        return not (self == other)

    def __neg__(self) -> Function1D:
        return self.__class__(self.mesh, -self.values)

    def __pos__(self) -> Function1D:
        return self

    def __abs__(self) -> Function1D:
        return self.__class__(self.mesh, np.abs(self.values))

    def __add__(self, other) -> Function1D:
        cls = self.__class__
        if isinstance(other, cls):
            assert self.has_same_mesh(other)
            return cls(self.mesh, self.values+other.values)
        else:
            return cls(self.mesh, self.values + np.array(other))

    __radd__ = __add__

    def __sub__(self, other) -> Function1D:
        cls = self.__class__
        if isinstance(other, cls):
            assert self.has_same_mesh(other)
            return cls(self.mesh, self.values-other.values)
        else:
            return cls(self.mesh, self.values-np.array(other))

    def __rsub__(self, other) -> Function1D:
        return -self + other

    def __mul__(self, other) -> Function1D:
        cls = self.__class__
        if isinstance(other, cls):
            assert self.has_same_mesh(other)
            return cls(self.mesh, self.values*other.values)
        else:
            return cls(self.mesh, self.values*other)

    __rmul__ = __mul__

    def __truediv__(self, other) -> Function1D:
        cls = self.__class__
        if isinstance(other, cls):
            assert self.has_same_mesh(other)
            return cls(self.mesh, self.values/other.values)
        else:
            return cls(self.mesh, self.values/other)

    __rtruediv__ = __truediv__

    def __pow__(self, other) -> Function1D:
        return self.__class__(self.mesh, self.values**other)

    def _repr_html_(self) -> Figure:
        """Integration with jupyter_ notebooks."""
        return self.plot(show=False)

    @property
    def real(self) -> Function1D:
        """Return new :class:`Function1D` with the real part of self."""
        return self.__class__(self.mesh, self.values.real)

    @property
    def imag(self) -> Function1D:
        """Return new :class:`Function1D` with the imaginary part of self."""
        return self.__class__(self.mesh, self.values.real)

    def conjugate(self) -> Function1D:
        """Return new :class:`Function1D` with the complex conjugate."""
        return self.__class__(self.mesh, self.values.conjugate)

    def abs(self) -> Function1D:
        """Return :class:`Function1D` with the absolute value."""
        return self.__class__(self.mesh, np.abs(self.values))

    def to_file(self, path, fmt='%.18e', header='') -> None:
        """
        Save data in a text file. Use format fmr. A header is added at the beginning.
        """
        fmt = "%s %s\n" % (fmt, fmt)
        with open(path, "wt") as fh:
            if header: fh.write(header)
            for x, y in zip(self.mesh, self.values):
                fh.write(fmt % (x, y))

    def __repr__(self) -> str:
        return "%s at %s, size = %d" % (self.__class__.__name__, id(self), len(self))

    def __str__(self) -> str:
        stream = StringIO()
        for x, y in zip(self.mesh, self.values):
            stream.write("%.18e %.18e\n" % (x, y))
        return "".join(stream.getvalue())

    def has_same_mesh(self, other: Function1D) -> bool:
        """True if self and other have the same mesh."""
        if self.h is None and other.h is None:
            # Generic meshes.
            return np.allclose(self.mesh, other.mesh)
        else:
            # Check for linear meshes
            return len(self.mesh) == len(other.mesh) and self.h == other.h

    @property
    def bma(self) -> float:
        """Return b-a. f(x) is defined in [a,b]"""
        return self.mesh[-1] - self.mesh[0]

    @property
    def max(self) -> float:
        """Max of f(x) if f is real, max of :math:`|f(x)|` if complex."""
        if not self.iscomplexobj:
            return self.values.max()
        else:
            # Max of |z|
            return np.max(np.abs(self.values))

    @property
    def min(self) -> float:
        """Min of f(x) if f is real, min of :math:`|f(x)|` if complex."""
        if not self.iscomplexobj:
            return self.values.min()
        else:
            return np.max(np.abs(self.values))

    @property
    def iscomplexobj(self) -> bool:
        """
        Check if values is array of complex numbers.
        The type of the input is checked, not the value. Even if the input
        has an imaginary part equal to zero, `np.iscomplexobj` evaluates to True.
        """
        return np.iscomplexobj(self.values)

    @lazy_property
    def h(self) -> Union[float, None]:
        """The spacing of the mesh. None if mesh is not homogeneous."""
        return self.dx[0] if np.allclose(self.dx[0], self.dx) else None

    @lazy_property
    def dx(self) -> np.ndarray:
        """
        |numpy-array| of len(self) - 1 elements giving the distance between two
        consecutive points of the mesh, i.e. dx[i] = ||x[i+1] - x[i]||.
        """
        dx = np.zeros(len(self)-1)
        for (i, x) in enumerate(self.mesh[:-1]):
            dx[i] = self.mesh[i+1] - x
        return dx

    def find_mesh_index(self, value) -> int:
        """
        Return the index of the first point in the mesh whose value is >= value
        -1 if not found
        """
        for i, x in enumerate(self.mesh):
            if x >= value:
                return i
        return -1

    def finite_diff(self, order: int = 1, acc: int = 4) -> Function1D:
        """
        Compute the derivatives by finite differences.

        Args:
            order: Order of the derivative.
            acc: Accuracy. 4 is fine in many cases.

        Returns:
            :class:`Function1D` instance with the derivative.
        """
        if self.h is None:
            raise ValueError("Finite differences with inhomogeneous meshes are not supported")

        return self.__class__(self.mesh, finite_diff(self.values, self.h, order=order, acc=acc))

    def integral(self, start=0, stop=None) -> Function1D:
        r"""
        Cumulatively integrate y(x) from start to stop using the composite trapezoidal rule.

        Returns:
            :class:`Function1D` with :math:`\int y(x) dx`
        """
        if stop is None: stop = len(self.values) + 1
        x, y = self.mesh[start:stop], self.values[start:stop]
        try :
            from scipy.integrate import cumulative_trapezoid as cumtrapz
        except ImportError:
            from scipy.integrate import cumtrapz

        integ = cumtrapz(y, x=x, initial=0.0)

        return self.__class__(x, integ)

    @lazy_property
    def spline(self):
        """Cubic spline with s=0"""
        from scipy.interpolate import UnivariateSpline
        return UnivariateSpline(self.mesh, self.values, s=0)

    @property
    def spline_roots(self):
        """Zeros of the spline."""
        return self.spline.roots()

    def spline_on_mesh(self, mesh) -> Function1D:
        """Spline the function on the given mesh, returns :class:`Function1D` object."""
        return self.__class__(mesh, self.spline(mesh))

    def spline_derivatives(self, x):
        """Returns all derivatives of the spline at point x."""
        return self.spline.derivatives(x)

    def spline_integral(self, a=None, b=None):
        """
        Returns the definite integral of the spline of f between two given points a and b

        Args:
            a: First point. mesh[0] if a is None
            b: Last point. mesh[-1] if a is None
        """
        a = self.mesh[0] if a is None else a
        b = self.mesh[-1] if b is None else b
        return self.spline.integral(a, b)

    @lazy_property
    def integral_value(self):
        r"""Compute :math:`\int f(x) dx`."""
        return self.integral()[-1][1]

    @lazy_property
    def l1_norm(self) -> float:
        r"""Compute :math:`\int |f(x)| dx`."""
        return abs(self).integral()[-1][1]

    @lazy_property
    def l2_norm(self) -> float:
        r"""Compute :math:`\sqrt{\int |f(x)|^2 dx}`."""
        return np.sqrt((abs(self)**2).integral()[-1][1])

    def fft(self) -> Function1D:
        """Compute the FFT transform (negative sign)."""
        # Compute FFT and frequencies.
        from scipy import fftpack
        n, d = len(self), self.h
        fft_vals = fftpack.fft(self.values, n=n)
        freqs = fftpack.fftfreq(n, d=d)

        # Shift the zero-frequency component to the center of the spectrum.
        fft_vals = fftpack.fftshift(fft_vals)
        freqs = fftpack.fftshift(freqs)

        return self.__class__(freqs, fft_vals)

    def ifft(self, x0=None) -> Function1D:
        r"""Compute the FFT transform :math:`\int e+i`"""
        # Rearrange values in the standard order then perform IFFT.
        from scipy import fftpack
        n, d = len(self), self.h
        fft_vals = fftpack.ifftshift(self.values)
        fft_vals = fftpack.ifft(fft_vals, n=n)

        # Compute the mesh of the IFFT output.
        x0 = 0.0 if x0 is None else x0
        stop = 1./d - 1./(n*d) + x0
        mesh = np.linspace(x0, stop, num=n)

        return self.__class__(mesh, fft_vals)

    #def convolve_with_func1d(self, other):
    #    """Convolve self with other."""
    #    assert self.has_same_mesh(other)
    #    from scipy.signal import convolve
    #    conv = convolve(self.values, other.values, mode="same") * self.h
    #    return self.__class__(self.mesh, conv)

    #def gaussian_convolution(self, width, height=None):
    #    """Convolve data with a Gaussian of standard deviation ``width``."""
    #    from abipy.tools.numtools import gaussian
    #    gvals = gaussian(self.mesh, width, center=self.mesh[len(self)//2], height=height)
    #    return self.convolve_with_func1d(Function1D(self.mesh, gvals))

    #def lorentzian_convolution(self, gamma, height=None):
    #    """Convolve data with a Lorentzian of half-width at half-maximum ``gamma``"""
    #    from abipy.tools.numtools import lorentzian
    #    lvals = lorentzian(self.mesh, gamma, center=self.mesh[len(self)//2], height=height)
    #    return self.convolve_with_func1d(Function1D(self.mesh, lvals))

    #def smooth(self, window_len=11, window="hanning"):
    #    from abipy.tools.numtools import smooth
    #    smooth_vals = smooth(self.values, window_len=window_len, window=window)
    #    return self.__class__(self.mesh, smooth_vals)

    #def real_from_kk(self, with_div=True):
    #    """
    #    Compute the Kramers-Kronig transform of the imaginary part
    #    to get the real part. Assume self represents the Fourier
    #    transform of a response function.

    #    Args:
    #        with_div: True if the divergence should be treated numerically.
    #            If False, the divergence is ignored, results are less accurate
    #            but the calculation is faster.

    #    .. seealso:: <https://en.wikipedia.org/wiki/Kramers%E2%80%93Kronig_relations>
    #    """
    #    from scipy.integrate import cumtrapz, quad
    #    from scipy.interpolate import UnivariateSpline
    #    wmesh = self.mesh
    #    num = np.array(self.values.imag * wmesh, dtype=np.double)

    #    if with_div:
    #        spline = UnivariateSpline(self.mesh, num, s=0)

    #    kk_values = np.empty(len(self))
    #    for i, w in enumerate(wmesh):
    #        den = wmesh**2 - w**2
    #        # Singularity is treated below.
    #        den[i] = 1
    #        f = num / den
    #        f[i] = 0
    #        integ = cumtrapz(f, x=wmesh)
    #        kk_values[i] = integ[-1]

    #        if with_div:
    #            func = lambda x: spline(x) / (x**2 - w**2)
    #            w0 = w - self.h
    #            w1 = w + self.h
    #            y, abserr = quad(func, w0, w1, points=[w])
    #            kk_values[i] += y

    #    return self.__class__(self.mesh, (2 / np.pi) * kk_values)

    #def imag_from_kk(self, with_div=True):
    #    """
    #    Compute the Kramers-Kronig transform of the real part
    #    to get the imaginary part. Assume self represents the Fourier
    #    transform of a response function.

    #    Args:
    #        with_div: True if the divergence should be treated numerically.
    #            If False, the divergence is ignored, results are less accurate
    #            but the calculation is faster.

    #    .. seealso:: <https://en.wikipedia.org/wiki/Kramers%E2%80%93Kronig_relations>
    #    """
    #    from scipy.integrate import cumtrapz, quad
    #    from scipy.interpolate import UnivariateSpline
    #    wmesh = self.mesh
    #    num = np.array(self.values.real, dtype=np.double)

    #    if with_div:
    #        spline = UnivariateSpline(self.mesh, num, s=0)

    #    kk_values = np.empty(len(self))
    #    for i, w in enumerate(wmesh):
    #        den = wmesh**2 - w**2
    #        # Singularity is treated below.
    #        den[i] = 1
    #        f = num / den
    #        f[i] = 0
    #        integ = cumtrapz(f, x=wmesh)
    #        kk_values[i] = integ[-1]

    #        if with_div:
    #            func = lambda x: spline(x) / (x**2 - w**2)
    #            w0 = w - self.h
    #            w1 = w + self.h
    #            y, abserr = quad(func, w0, w1, points=[w])
    #            kk_values[i] += y

    #    return self.__class__(self.mesh, -(2 / np.pi) * wmesh * kk_values)

    def plot_ax(self, ax, exchange_xy=False, normalize=False, xfactor=1, yfactor=1, *args, **kwargs) -> list:
        """
        Helper function to plot self on axis ax.

        Args:
            ax: |matplotlib-Axes|.
            exchange_xy: True to exchange the axis in the plot.
            args: Positional arguments passed to ax.plot
            normalize: Normalize the ydata to 1.
            xfactor, yfactor: xvalues and yvalues are multiplied by this factor before plotting.
            kwargs: Keyword arguments passed to ``matplotlib``. Accepts

        ==============  ===============================================================
        kwargs          Meaning
        ==============  ===============================================================
        cplx_mode       string defining the data to print.
                        Possible choices are (case-insensitive): `re` for the real part
                        "im" for the imaginary part, "abs" for the absolute value.
                        "angle" to display the phase of the complex number in radians.
                        Options can be concatenated with "-"
        ==============  ===============================================================

        Returns:
            List of lines added.
        """
        if self.iscomplexobj:
            cplx_mode = kwargs.pop("cplx_mode", "re-im")
        else:
            cplx_mode = kwargs.pop("cplx_mode", "re")

        lines = []
        for c in cplx_mode.lower().split("-"):
            xx, yy = self.mesh, data_from_cplx_mode(c, self.values)
            if xfactor != 1: xx = xx * xfactor
            if yfactor != 1: yy = yy * yfactor
            if normalize: yy = yy / np.max(yy)

            if exchange_xy:
                xx, yy = yy, xx

            lines.extend(ax.plot(xx, yy, *args, **kwargs))

        return lines

    @add_fig_kwargs
    def plot(self, ax=None, **kwargs) -> Figure:
        """
        Plot the function with matplotlib.

        Args:
            ax: |matplotlib-Axes| or None if a new figure should be created.

        ==============  ===============================================================
        kwargs          Meaning
        ==============  ===============================================================
        exchange_xy     True to exchange x- and y-axis (default: False)
        ==============  ===============================================================

        Returns: |matplotlib-Figure|.
        """
        ax, fig, plt = get_ax_fig_plt(ax=ax)
        ax.grid(True)
        exchange_xy = kwargs.pop("exchange_xy", False)
        self.plot_ax(ax, exchange_xy=exchange_xy, **kwargs)

        return fig

    def plotly_traces(self, fig, rcd=None, exchange_xy=False, xfactor=1, yfactor=1, *args, **kwargs):
        """
        Helper function to plot the function with plotly.

        Args:
            fig: plotly.graph_objects.Figure.
            rcd: PlotlyRowColDesc object used when fig is not None to specify the (row, col) of the subplot in the grid.
            exchange_xy: True to exchange the x and y in the plot.
            xfactor, yfactor: xvalues and yvalues are multiplied by this factor before plotting.
            args: Positional arguments passed to 'plotly.graph_objects.Scatter'
            kwargs: Keyword arguments passed to 'plotly.graph_objects.Scatter'.
                Accepts also AbiPy specific kwargs:

        ==============  ===============================================================
        kwargs          Meaning
        ==============  ===============================================================
        cplx_mode       string defining the data to print.
                        Possible choices are (case-insensitive): `re` for the real part
                        "im" for the imaginary part, "abs" for the absolute value.
                        "angle" to display the phase of the complex number in radians.
                        Options can be concatenated with "-"
        ==============  ===============================================================
        """
        rcd = PlotlyRowColDesc.from_object(rcd)
        ply_row, ply_col = rcd.ply_row, rcd.ply_col

        import plotly.graph_objects as go

        if self.iscomplexobj:
            cplx_mode = kwargs.pop("cplx_mode", "re-im")
        else:
            cplx_mode = kwargs.pop("cplx_mode", "re")

        showlegend = False
        if "name" in kwargs: showlegend = True
        showlegend = kwargs.pop("showlegend", showlegend)

        for c in cplx_mode.lower().split("-"):
            xx, yy = self.mesh, data_from_cplx_mode(c, self.values)
            if xfactor != 1: xx = xx * xfactor
            if yfactor != 1: yy = yy * yfactor

            if exchange_xy:
                xx, yy = yy, xx

            fig.add_trace(go.Scatter(x=xx, y=yy, mode="lines", showlegend=showlegend, *args, **kwargs),
                          row=ply_row, col=ply_col)

    @add_plotly_fig_kwargs
    def plotly(self, exchange_xy=False, fig=None, rcd=None, **kwargs):
        """
        Plot the function with plotly.

        Args:
            exchange_xy: True to exchange x- and y-axis (default: False)
            fig: plotly figure or None if a new figure should be created.
            rcd: PlotlyRowColDesc object used when fig is not None to specify the (row, col)
                of the subplot in the grid.

        Returns: plotly-Figure
        """
        fig, _ = get_fig_plotly(fig=fig)
        rcd = PlotlyRowColDesc.from_object(rcd)
        self.plotly_traces(fig, rcd=rcd, exchange_xy=exchange_xy, **kwargs)

        return fig
