"""Tests for psps module."""
import numpy as np
import abipy.data as abidata
import abipy.core

from abipy.core.testing import AbipyTest
from abipy.electrons.psps import PspsFile, PspsRobot


class PspsFileTestCase(AbipyTest):

    def test_psps_nc_silicon(self):
        """Testing PSPS.nc file with Ga.oncvpsp"""
        pseudo = abidata.pseudo("Ga.oncvpsp")

        with pseudo.open_pspsfile(ecut=10) as psps:
            repr(psps); print(psps)
            r = psps.r
            assert r.usepaw == 0 and r.ntypat == 1
            assert not psps.params

            robot = PspsRobot.from_files([psps.filepath])
            repr(psps); print(psps)

            all_projs = psps.r.read_projectors()
            for itypat, p_list in enumerate(all_projs):
                for p in p_list:
                    assert p.to_string(verbose=1)

            if self.has_matplotlib():
                # psps plots.
                assert psps.plot(what="all", with_qn=True, show=False)
                assert psps.plot_tcore_rspace(ax=None, ders=(0, 1, 2, 3), scale=1.0, rmax=3.0, show=False)
                assert psps.plot_tcore_qspace(ax=None, ders=(0,), with_fact=True, with_qn=0, scale=1.0, show=False)
                assert psps.plot_q2vq(ax=None, ders=(0,), with_qn=0, with_fact=True, scale=None, show=False)
                assert psps.plot_ffspl(ax=None, ecut_ffnl=None, ders=(0,), l_select=None,
                                       with_qn=0, with_fact=False, scale=None, show=False)
                # robot plots.
                assert robot.plot_tcore_rspace(ders=(0, 1, 2, 3), with_qn=0, scale=None, fontsize=8, show=False)
                assert robot.plot_tcore_qspace(ders=(0, 1), with_qn=0, scale=None, fontsize=8, show=False)
                assert robot.plot_q2vq(ders=(0, 1), with_qn=0, with_fact=True, scale=None, fontsize=8, show=False)
                assert robot.plot_ffspl(ecut_ffnl=None, ders=(0, 1), with_qn=0, scale=None, fontsize=8, show=False)
