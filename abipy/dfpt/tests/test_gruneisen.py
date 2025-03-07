"""Tests for Grunesein module."""
import os
import numpy as np
import abipy.data as abidata

from abipy.core.testing import AbipyTest
from abipy import abilab
from abipy.dfpt.gruneisen import GrunsNcFile, calculate_gruns_finite_differences


class GrunsFileTest(AbipyTest):

    def test_gruns_ncfile(self):
        """Testsing GrunsFile."""
        with abilab.abiopen(abidata.ref_file("mg2si_GRUNS.nc")) as ncfile:
            repr(ncfile); str(ncfile)
            assert ncfile.structure.formula == "Mg2 Si1"
            assert ncfile.iv0 == 1
            #assert len(ncfile.volumes) == 3
            assert not ncfile.params

            d = ncfile.phdoses
            assert d is ncfile.phdoses
            assert "wmesh" in d
            assert len(ncfile.phbands_qpath_vol) == 3
            assert d.qpoints.is_ibz

            assert ncfile.split_gruns
            assert ncfile.split_dwdq

            df = ncfile.to_dataframe()
            assert "grun" in df and "freq" in df

            assert ncfile.phdos

            self.assertAlmostEqual(ncfile.average_gruneisen(t=None, squared=True, limit_frequencies=None),
                                   1.4206573918609795, places=5)
            self.assertAlmostEqual(ncfile.average_gruneisen(t=None, squared=False, limit_frequencies="debye"),
                                   1.2121437911186166, places=5)
            self.assertAlmostEqual(ncfile.average_gruneisen(t=None, squared=False, limit_frequencies="acoustic"),
                                   1.213016691881557, places=5)
            self.assertAlmostEqual(ncfile.thermal_conductivity_slack(squared=True, limit_frequencies=None),
                                   14.553100876473687, places=4)
            self.assertAlmostEqual(ncfile.thermal_conductivity_slack(squared=True, limit_frequencies=None, t=300),
                                   14.43141396698724, places=4)
            self.assertAlmostEqual(ncfile.debye_temp, 429.05702577371898, places=4)
            self.assertAlmostEqual(ncfile.acoustic_debye_temp, 297.49152615955893, places=4)

            ncfile.grun_vals_finite_differences(match_eigv=False)
            ncfile.gvals_qibz_finite_differences(match_eigv=False)

            if self.has_matplotlib():
                assert ncfile.plot_phdoses(title="PHDOSes", show=False)
                assert ncfile.plot_phdoses(with_idos=False, xlims=None, show=False)

                # Arrow up for positive values, down for negative values.
                assert ncfile.plot_phbands_with_gruns(title="bands with gamma markers + PHDOSes", show=False)
                assert ncfile.plot_phbands_with_gruns(with_doses=None, gamma_fact=2, units="cm-1", show=False)
                assert ncfile.plot_phbands_with_gruns(fill_with="groupv", gamma_fact=2, units="cm-1", show=False)
                assert ncfile.plot_phbands_with_gruns(fill_with="gruns_fd", gamma_fact=2, units="cm-1", show=False)

                plotter = ncfile.get_plotter()
                assert plotter.combiboxplot(show=False)
                assert plotter.animate(show=False)

                assert ncfile.plot_gruns_scatter(units='cm-1', show=False)
                assert ncfile.plot_gruns_scatter(values="groupv", units='cm-1', show=False)
                assert ncfile.plot_gruns_scatter(values="gruns_fd", units='cm-1', show=False)

                assert ncfile.plot_gruns_bs(match_bands=True, show=False)
                assert ncfile.plot_gruns_bs(values="groupv", match_bands=False, show=False)
                assert ncfile.plot_gruns_bs(values="gruns_fd", match_bands=False, show=False)

            if self.has_nbformat():
                assert ncfile.write_notebook(nbpath=self.get_tmpname(text=True))

    def test_from_ddb_list(self):
        """Testsing GrunsFile generation from ddblist."""

        # shuffled list as the function should also sort the values
        strains = [0, +4, -2, 2, -4]
        path = os.path.join(abidata.dirpath, "refs", "si_qha")
        ddb_list = [os.path.join(path, "mp-149_{:+d}_DDB".format(s)) for s in strains]

        g = GrunsNcFile.from_ddb_list(ddb_list, ndivsm=3, nqsmall=3)


class FunctionsTest(AbipyTest):

    def test_calculate_gruns_finite_differences(self):
        phfreqs = np.array([[[0, 0, 0]], [[1, 2, 3]], [[2, 6, 4]]])
        eig = np.array([[[[1, 0, 0], [0, 1, 0], [0, 0, 1]]], [[[1, 0, 0], [0, 0, 1], [0, 1, 0]]],
               [[[1, 0, 0], [0, 1, 0], [0, 0, 1]]]])

        g = calculate_gruns_finite_differences(phfreqs, eig, iv0=1, volume=1, dv=1)
        self.assert_equal(g, [[-1, -1, -1]])
