"""
FWHM Analysis Widget for PIXIE-16 Scope
Provides UI for ROI selection and Gaussian peak fitting on energy histograms.
"""

import numpy as np
from datetime import datetime
from typing import Dict, List, Tuple, Any

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox,
    QLabel, QPushButton, QComboBox,
    QCheckBox, QTableWidget, QTableWidgetItem, QHeaderView,
    QMessageBox
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
import pyqtgraph as pg

from .fwhm_analyzer import FWHMAnalyzer


class ROISelector:
    def __init__(self, plot_widget, parent_widget=None):
        self.plot_widget = plot_widget
        self.parent_widget = parent_widget
        self.roi_regions = []
        self.roi_data = []
        self.roi_counter = 1
        self.roi_colors = [
            (255, 255, 0, 80), (255, 0, 255, 80), (0, 255, 255, 80),
            (255, 165, 0, 80), (0, 255, 0, 80), (255, 0, 0, 80),
            (128, 0, 128, 80), (0, 128, 255, 80),
        ]

    def add_roi(self, start: float, end: float, name: str = None) -> int:
        if name is None:
            name = f"ROI {self.roi_counter}"
            self.roi_counter += 1
        color_idx = len(self.roi_regions) % len(self.roi_colors)
        c = self.roi_colors[color_idx]
        region = pg.LinearRegionItem(
            values=(start, end),
            brush=pg.mkBrush(*c), pen=pg.mkPen(c[:3], width=2)
        )
        self.plot_widget.addItem(region)
        if self.parent_widget:
            region.sigRegionChangeFinished.connect(
                lambda: self.parent_widget.update_roi_status()
            )
        self.roi_regions.append(region)
        self.roi_data.append((start, end, name))
        return len(self.roi_regions) - 1

    def clear_all_rois(self):
        for r in self.roi_regions:
            self.plot_widget.removeItem(r)
        self.roi_regions.clear()
        self.roi_data.clear()
        self.roi_counter = 1

    def get_all_rois(self) -> List[Tuple[float, float, str]]:
        out = []
        for i, (_, _, name) in enumerate(self.roi_data):
            if 0 <= i < len(self.roi_regions):
                s, e = self.roi_regions[i].getRegion()
                out.append((float(s), float(e), name))
        return out


# ═══════════════════════════════════════════════════════════════════════
# Results table
# ═══════════════════════════════════════════════════════════════════════

class FWHMResultsTable(QTableWidget):
    def __init__(self):
        super().__init__()
        self._units = "bins"
        self._setup()

    def _setup(self):
        self._update_headers()
        self.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.setAlternatingRowColors(True)
        self.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)

    def _update_headers(self):
        u = self._units
        headers = [
            "Ch", "ROI",
            f"Mean ({u})", f"FWHM ({u})",
            "Net Area", "Signif.", "chi-sq",
        ]
        self.setColumnCount(len(headers))
        self.setHorizontalHeaderLabels(headers)

    def add_peak(self, ch, roi_name, mean, mean_err, fwhm, fwhm_err,
                 net_area, area_err, significance, redchi):
        row = self.rowCount()
        self.insertRow(row)

        def _ve(v, e):
            if e and e > 0:
                return f"{v:.2f} \u00b1{e:.2f}"
            return f"{v:.2f}"

        items = [
            str(ch), roi_name,
            _ve(mean, mean_err), _ve(fwhm, fwhm_err),
            _ve(net_area, area_err),
            f"{significance:.1f}\u03c3" if significance else "-",
            f"{redchi:.3f}" if redchi is not None else "-",
        ]
        for col, text in enumerate(items):
            cell = QTableWidgetItem(text)
            cell.setFlags(cell.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.setItem(row, col, cell)

    def clear_results(self):
        self.setRowCount(0)


# ═══════════════════════════════════════════════════════════════════════
# Main widget
# ═══════════════════════════════════════════════════════════════════════

class FWHMAnalysisWidget(QWidget):
    analysis_completed = pyqtSignal(list)
    roi_changed = pyqtSignal()

    def __init__(self, spectrum_plotter=None):
        super().__init__()
        self.spectrum_plotter = spectrum_plotter
        self.analyzer = FWHMAnalyzer()
        self.roi_selector = None
        self.current_results = []
        self._fit_plot_items = []

        self.init_ui()
        self.setup_connections()
        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self.run_analysis)

    # ── UI ────────────────────────────────────────────────────────────

    def init_ui(self):
        layout = QVBoxLayout()
        layout.addWidget(self._create_roi_controls())
        layout.addWidget(self._create_analysis_controls())
        layout.addWidget(self._create_results_group())
        self.setLayout(layout)

    def _create_roi_controls(self) -> QGroupBox:
        group = QGroupBox("Region of Interest")
        layout = QVBoxLayout()
        info = QLabel("Add a draggable region, then drag its edges over a peak.")
        info.setStyleSheet("QLabel { color: gray; font-size: 10px; }")
        layout.addWidget(info)
        row = QHBoxLayout()
        self.add_roi_btn = QPushButton("Add ROI")
        self.add_roi_btn.setToolTip("Places a draggable highlight on the spectrum.")
        self.add_roi_btn.setStyleSheet("QPushButton { background-color: #4CAF50; color: white; }")
        row.addWidget(self.add_roi_btn)
        self.clear_roi_btn = QPushButton("Clear All")
        row.addWidget(self.clear_roi_btn)
        row.addStretch()
        layout.addLayout(row)
        self.roi_status_label = QLabel("No ROIs defined")
        layout.addWidget(self.roi_status_label)
        group.setLayout(layout)
        return group

    def _create_analysis_controls(self) -> QGroupBox:
        group = QGroupBox("Analysis")
        layout = QHBoxLayout()
        self.analyze_btn = QPushButton("Fit")
        self.analyze_btn.setStyleSheet("QPushButton { font-weight: bold; }")
        self.analyze_btn.setToolTip("Fit Gaussian peak(s) inside each ROI.")
        layout.addWidget(self.analyze_btn)
        self.auto_update_check = QCheckBox("Auto-refit")
        self.auto_update_check.setToolTip(
            "Re-runs the fit every 2 s during live acquisition.\n"
            "The fit improves as the histogram accumulates counts.")
        layout.addWidget(self.auto_update_check)
        layout.addStretch()
        layout.addWidget(QLabel("Bkg:"))
        self.bg_combo = QComboBox()
        self.bg_combo.addItems(["linear", "quadratic", "constant"])
        self.bg_combo.setToolTip("Background model subtracted under the Gaussian.")
        layout.addWidget(self.bg_combo)
        group.setLayout(layout)
        return group

    def _create_results_group(self) -> QGroupBox:
        group = QGroupBox("Fit Results")
        layout = QVBoxLayout()
        self.results_table = FWHMResultsTable()
        layout.addWidget(self.results_table)
        row = QHBoxLayout()
        self.export_btn = QPushButton("Export")
        row.addWidget(self.export_btn)
        self.clear_results_btn = QPushButton("Clear")
        row.addWidget(self.clear_results_btn)
        row.addStretch()
        self.stats_label = QLabel("")
        row.addWidget(self.stats_label)
        layout.addLayout(row)
        group.setLayout(layout)
        return group

    # ── Connections ───────────────────────────────────────────────────

    def setup_connections(self):
        self.add_roi_btn.clicked.connect(self.add_roi)
        self.clear_roi_btn.clicked.connect(self.clear_all_rois)
        self.analyze_btn.clicked.connect(self.run_analysis)
        self.auto_update_check.toggled.connect(self._toggle_auto)
        self.clear_results_btn.clicked.connect(self.clear_results)
        self.export_btn.clicked.connect(self.export_results)

    def connect_to_plotter(self, spectrum_plotter):
        self.spectrum_plotter = spectrum_plotter
        if hasattr(spectrum_plotter, 'plot_widget'):
            self.roi_selector = ROISelector(spectrum_plotter.plot_widget, parent_widget=self)
        self.update_roi_status()

    # ── ROI management ───────────────────────────────────────────────

    def add_roi(self):
        if not self.roi_selector:
            QMessageBox.warning(self, "No Plot", "No spectrum plot connected")
            return
        if self.spectrum_plotter and hasattr(self.spectrum_plotter, 'plot_widget'):
            vr = self.spectrum_plotter.plot_widget.getViewBox().viewRange()[0]
            span = vr[1] - vr[0]
            self.roi_selector.add_roi(vr[0] + span * 0.33, vr[0] + span * 0.66)
        else:
            self.roi_selector.add_roi(500, 1500)
        self.update_roi_status()
        self.roi_changed.emit()

    def clear_all_rois(self):
        if self.roi_selector:
            self.roi_selector.clear_all_rois()
        self._clear_fit_plots()
        self.update_roi_status()
        self.roi_changed.emit()

    def update_roi_status(self):
        if not self.roi_selector:
            self.roi_status_label.setText("No plot connected")
            return
        rois = self.roi_selector.get_all_rois()
        if not rois:
            self.roi_status_label.setText("No ROIs — click 'Add ROI'")
        else:
            self.roi_status_label.setText(
                "  ".join(f"{n}: {s:.0f}\u2013{e:.0f}" for s, e, n in rois))

    # ── Coordinate helpers ───────────────────────────────────────────

    def _energy_to_bin(self, energy, erange, nbins):
        frac = (energy - erange[0]) / (erange[1] - erange[0])
        return int(np.clip(frac * nbins, 0, nbins - 1))

    # ── Data retrieval ───────────────────────────────────────────────

    def get_current_spectrum_data(self) -> Dict[int, np.ndarray]:
        if not self.spectrum_plotter:
            return {}
        if hasattr(self.spectrum_plotter, 'get_histogram_data'):
            return self.spectrum_plotter.get_histogram_data()
        data = {}
        if hasattr(self.spectrum_plotter, 'energy_data'):
            for ch, deq in self.spectrum_plotter.energy_data.items():
                if len(deq) > 0:
                    er = getattr(self.spectrum_plotter, 'energy_range', (0, 65535))
                    nb = getattr(self.spectrum_plotter, 'bins', 4096)
                    hist, _ = np.histogram(list(deq), bins=nb, range=er)
                    data[ch] = hist
        return data

    # ── Core analysis ────────────────────────────────────────────────

    def run_analysis(self):
        if not self.roi_selector:
            return
        try:
            spectra = self.get_current_spectrum_data()
            if not spectra:
                self.stats_label.setText("No spectrum data")
                return
            rois = self.roi_selector.get_all_rois()
            if not rois:
                self.stats_label.setText("No ROIs defined")
                return

            erange = getattr(self.spectrum_plotter, 'energy_range', (0, 4096))
            nbins = getattr(self.spectrum_plotter, 'bins', 1000)
            bw = (erange[1] - erange[0]) / nbins
            bin_centers = np.linspace(erange[0] + bw/2, erange[1] - bw/2, nbins)

            self.current_results.clear()
            self.results_table.clear_results()
            self._clear_fit_plots()
            self.analyzer.default_background = self.bg_combo.currentText()

            n_peaks = 0
            for ch, spectrum in spectra.items():
                for roi_e0, roi_e1, roi_name in rois:
                    b0 = self._energy_to_bin(roi_e0, erange, nbins)
                    b1 = self._energy_to_bin(roi_e1, erange, nbins)
                    if b0 >= b1:
                        continue

                    results = self.analyzer.analyze_roi(spectrum, b0, b1, channel_id=ch)
                    for result in results:
                        result.timestamp = datetime.now()

                        for pi in range(len(result.peak_centers)):
                            ctr_bin = result.peak_centers[pi]
                            ctr_err = result.center_errors[pi] if pi < len(result.center_errors) else 0
                            sigma = result.peak_sigmas[pi] if pi < len(result.peak_sigmas) else 0
                            sig_err = result.sigma_errors[pi] if pi < len(result.sigma_errors) else 0
                            fwhm_bins = sigma * 2.355
                            fwhm_err_bins = sig_err * 2.355
                            area_err = result.amplitude_errors[pi] if pi < len(result.amplitude_errors) else 0
                            net_area = result.peak_areas_net[pi] if pi < len(result.peak_areas_net) else (
                                result.peak_areas[pi] if pi < len(result.peak_areas) else 0)
                            signif = result.peak_significances[pi] if pi < len(result.peak_significances) else 0

                            self.results_table.add_peak(
                                ch, roi_name,
                                mean=ctr_bin,
                                mean_err=ctr_err,
                                fwhm=fwhm_bins,
                                fwhm_err=fwhm_err_bins,
                                net_area=net_area,
                                area_err=area_err,
                                significance=signif,
                                redchi=result.reduced_chi2,
                            )
                            n_peaks += 1

                        if result.fit_success:
                            self._plot_fit_overlay(result, bin_centers)

                    self.current_results.extend(results)

            self.stats_label.setText(f"{n_peaks} peak(s) fitted" if n_peaks else "No peaks found")
            self.analysis_completed.emit(self.current_results)

        except Exception as e:
            self.stats_label.setText(f"Error: {e}")
            import traceback
            traceback.print_exc()

    # ── Plot overlay ─────────────────────────────────────────────────

    def _plot_fit_overlay(self, result, bin_centers):
        if not self.spectrum_plotter or not hasattr(self.spectrum_plotter, 'plot_widget'):
            return
        pw = self.spectrum_plotter.plot_widget
        bc = np.arange(len(bin_centers))

        for center, sigma, amplitude in zip(
            result.peak_centers, result.peak_sigmas, result.peak_amplitudes
        ):
            xb = np.linspace(max(0, center - 4*sigma), min(len(bin_centers)-1, center + 4*sigma), 200)
            yg = (amplitude / (sigma * np.sqrt(2 * np.pi))) * np.exp(-0.5 * ((xb - center) / sigma) ** 2)
            xe = np.interp(xb, bc, bin_centers)
            pen = pg.mkPen(color=(255, 0, 0, 180), width=2, style=pg.QtCore.Qt.PenStyle.DashLine)
            curve = pg.PlotCurveItem(xe, yg, pen=pen)
            pw.addItem(curve)
            self._fit_plot_items.append(curve)

        xb = np.arange(result.roi_start, result.roi_end + 1, dtype=float)
        total = np.zeros_like(xb)
        for pname, val in result.background_params.items():
            if "slope" in pname:
                total += val * xb
            elif "intercept" in pname or pname.endswith("_c"):
                total += val
        for center, sigma, amplitude in zip(
            result.peak_centers, result.peak_sigmas, result.peak_amplitudes
        ):
            total += (amplitude / (sigma * np.sqrt(2 * np.pi))) * np.exp(-0.5 * ((xb - center) / sigma) ** 2)
        xe = np.interp(xb, bc, bin_centers)
        pen = pg.mkPen(color=(0, 255, 0, 200), width=2)
        curve = pg.PlotCurveItem(xe, total, pen=pen)
        pw.addItem(curve)
        self._fit_plot_items.append(curve)

    # ── Cleanup ──────────────────────────────────────────────────────

    def _clear_fit_plots(self):
        if self.spectrum_plotter and hasattr(self.spectrum_plotter, 'plot_widget'):
            for item in self._fit_plot_items:
                try:
                    self.spectrum_plotter.plot_widget.removeItem(item)
                except Exception:
                    pass
        self._fit_plot_items.clear()

    def _toggle_auto(self, on):
        if on:
            self.update_timer.start(2000)
        else:
            self.update_timer.stop()

    def clear_results(self):
        self.current_results.clear()
        self.results_table.clear_results()
        self._clear_fit_plots()
        self.stats_label.setText("")

    # ── Export ────────────────────────────────────────────────────────

    def export_results(self):
        if not self.current_results:
            QMessageBox.information(self, "No Data", "No results to export")
            return
        try:
            from .data_manager import DataSaver, DataSettingsManager
            saver = DataSaver(DataSettingsManager())
            success = saver.save_fwhm_analysis_data(
                self.get_analysis_data(),
                {'instrument': 'pixie16', 'analysis_type': 'fwhm_peak_analysis',
                 'data_source': 'list_mode_histogram'},
                parent=self)
            if success:
                if QMessageBox.question(
                    self, "Saved", "Clear results?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                ) == QMessageBox.StandardButton.Yes:
                    self.clear_results()
        except Exception as e:
            QMessageBox.critical(self, "Export Error", str(e))

    def get_analysis_data(self) -> Dict[str, Any]:
        peaks = []
        for r in self.current_results:
            for i in range(len(r.peak_centers)):
                peaks.append({
                    'channel': r.channel,
                    'roi_start': r.roi_start, 'roi_end': r.roi_end,
                    'mean_bin': r.peak_centers[i],
                    'fwhm_bins': r.peak_fwhms[i] if i < len(r.peak_fwhms) else None,
                    'area': r.peak_areas[i] if i < len(r.peak_areas) else None,
                    'net_area': r.peak_areas_net[i] if i < len(r.peak_areas_net) else None,
                    'reduced_chi2': r.reduced_chi2,
                    'units': 'bins',
                    'timestamp': r.timestamp.isoformat() if r.timestamp else None,
                })
        return {
            'fwhm_results': peaks,
            'analysis_parameters': {
                'background_model': self.bg_combo.currentText(),
            },
            'rois': self.roi_selector.get_all_rois() if self.roi_selector else [],
        }
