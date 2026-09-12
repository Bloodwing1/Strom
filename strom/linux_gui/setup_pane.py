"""Guided setup: language, weather, prices, plug, and setup status."""

from __future__ import annotations

import os
from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets

from strom.linux_gui.setup_files import (
    PRICE_FILE,
    WEATHER_FILE,
    SetupError,
    SetupStatus,
    read_setup_status,
    read_tapo_credentials,
    save_api_key,
    save_tapo_credentials,
)
from strom.linux_gui.ui_text import (
    _CONTRIBUTE_URL,
    _PRICE_HELP_TEXT,
    _PRICE_SIGNUP_URL,
    _STEP_SHORT_NAMES,
    _TAPO_HELP_TEXT,
    _WEATHER_HELP_TEXT,
    _WEATHER_SIGNUP_URL,
    city_is_valid,
)
from strom.linux_gui.theme import repolish
from strom.linux_gui.window_base import WindowBase
from strom.plug import PlugCredentials


class SetupPaneMixin(WindowBase):
    def _build_accounts_group(self, parent: QtWidgets.QWidget) -> QtWidgets.QWidget:
        page = QtWidgets.QWidget(parent)
        layout = QtWidgets.QHBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(20)

        self._step_indicator = QtWidgets.QFrame(page)
        self._step_indicator.setObjectName("stepIndicator")
        self._step_indicator.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Maximum,
            QtWidgets.QSizePolicy.Policy.Preferred,
        )
        indicator_row = QtWidgets.QVBoxLayout(self._step_indicator)
        indicator_row.setContentsMargins(12, 18, 12, 14)
        indicator_row.setSpacing(6)
        setup_label = QtWidgets.QLabel("SETUP", self._step_indicator)
        setup_label.setObjectName("setupLabel")
        indicator_row.addWidget(setup_label)
        indicator_row.addSpacing(8)
        self._step_list = QtWidgets.QListWidget(self._step_indicator)
        self._step_list.setAccessibleName("Setup steps")
        self._step_list.addItems(_STEP_SHORT_NAMES)
        self._step_list.currentRowChanged.connect(self._navigate_step)
        indicator_row.addWidget(self._step_list)
        indicator_row.addStretch(1)
        layout.addWidget(self._step_indicator)
        layout.setAlignment(
            self._step_indicator, QtCore.Qt.AlignmentFlag.AlignTop
        )

        workspace = QtWidgets.QWidget(page)
        workspace_layout = QtWidgets.QVBoxLayout(workspace)
        workspace_layout.setContentsMargins(0, 0, 0, 0)
        workspace_layout.setSpacing(14)
        # Steps share one area sized to the tallest step, so the navigation
        # buttons stay in place when the active step changes.
        self._account_pages = QtWidgets.QStackedWidget(page)
        for builder in (
            self._build_language_block, self._build_weather_block,
            self._build_price_block, self._build_tapo_block
        ):
            step_page = QtWidgets.QWidget(page)
            page_layout = QtWidgets.QVBoxLayout(step_page)
            page_layout.setContentsMargins(0, 0, 0, 0)
            card = QtWidgets.QFrame(step_page)
            card.setObjectName("setupCard")
            card_layout = QtWidgets.QVBoxLayout(card)
            card_layout.setContentsMargins(26, 24, 26, 24)
            card_layout.setSpacing(14)
            card_layout.addWidget(builder(card))
            page_layout.addWidget(card)
            page_layout.addStretch(1)
            self._account_pages.addWidget(step_page)
        workspace_layout.addWidget(self._account_pages)
        navigation = QtWidgets.QHBoxLayout()
        self._setup_later = QtWidgets.QPushButton("Set up later", page)
        self._setup_later.setFlat(True)
        self._setup_later.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self._setup_later.clicked.connect(self._finish_setup)
        navigation.addWidget(self._setup_later)
        navigation.addStretch(1)
        self._back_button = QtWidgets.QPushButton("Back", page)
        self._back_button.clicked.connect(lambda: self._show_step(
            self._account_pages.currentIndex() - 1
        ))
        self._next_button = QtWidgets.QPushButton("Continue", page)
        self._next_button.setObjectName("continueAction")
        self._next_button.setDefault(True)
        self._next_button.clicked.connect(self._continue_setup)
        navigation.addWidget(self._back_button)
        navigation.addSpacing(8)
        navigation.addWidget(self._next_button)
        workspace_layout.addLayout(navigation)
        self._advanced_toggle = QtWidgets.QCheckBox("Advanced settings", page)
        workspace_layout.addWidget(self._advanced_toggle)
        self._advanced_settings = QtWidgets.QWidget(page)
        workspace_layout.addWidget(self._advanced_settings)
        self._advanced_toggle.toggled.connect(self._advanced_settings.setVisible)
        self._advanced_settings.hide()
        self._build_advanced_settings(self._advanced_settings)
        workspace_layout.addStretch(1)
        layout.addWidget(workspace, 1)

        self._show_step(0)
        return page

    def _navigate_step(self, index: int) -> None:
        if index >= 0:
            self._show_step(index)
            self._step_list.setFocus()

    def _show_step(self, index: int) -> None:
        index = max(0, min(index, self._account_pages.count() - 1))
        self._account_pages.setCurrentIndex(index)
        self._back_button.setEnabled(index > 0 and not self._runner.is_active())
        self._next_button.setText(
            self._translated("Finish setup" if index == 3 else "Continue")
        )
        self._reserve_next_button_width()
        self._advanced_toggle.setVisible(index > 0)
        self._advanced_settings.setVisible(
            index > 0 and self._advanced_toggle.isChecked()
        )
        fields = (
            self._language,
            self._city,
            self._price_key_edit,
            self._tapo_ip,
        )
        fields[index].setFocus()
        self._sync_intro_visibility()
        self._sync_step_indicator()

    def _reserve_next_button_width(self) -> None:
        """Reserve room for the longer label so the row never shifts."""
        shown = self._next_button.text()
        width = 0
        for label in ("Continue", "Finish setup"):
            self._next_button.setText(self._translated(label))
            width = max(width, self._next_button.sizeHint().width())
        self._next_button.setText(shown)
        self._next_button.setMinimumWidth(width)

    def _sync_intro_visibility(self) -> None:
        """The intro paragraph is only useful before the language step."""
        self._intro_label.setVisible(
            self._pages.currentIndex() == 1
            or self._account_pages.currentIndex() == 0
        )

    def _continue_setup(self) -> None:
        index = self._account_pages.currentIndex()
        if index == 0:
            self.save_settings()
            self._show_step(1)
            return
        if index == 1 and not self._valid_location():
            self._refresh_setup_status()
            return
        account_index = index - 1
        fields = (
            (self._weather_key_edit,),
            (self._price_key_edit,),
            (self._tapo_email, self._tapo_password, self._tapo_ip),
        )
        # Save edits before leaving; a failed save keeps its inline error visible.
        if any(field.text() for field in fields[account_index]):
            save = (self._on_save_weather, self._on_save_price,
                    self._on_save_tapo)[account_index]
            if not save():
                return
        status = self._current_setup_status()
        ready = (status.weather_key_saved, status.price_key_saved, status.tapo_saved)
        if not ready[account_index]:
            chip = (self._weather_status, self._price_status,
                    self._tapo_status)[account_index]
            if account_index == 2 and status.tapo_ip_saved:
                message = "Click Test to verify the plug, then continue."
            else:
                message = (
                    "Add your details to continue, or choose Set up later."
                )
            self._set_chip(chip, self._translated(message), error=True)
            return
        self.save_settings()
        if index == 3:
            self._finish_setup()
        else:
            self._show_step(index + 1)

    def _finish_setup(self) -> None:
        self._refresh_setup_status()
        self.save_settings()
        self._pages.setCurrentIndex(1)
        self._run_button.setFocus()

    def _open_setup(self) -> None:
        self._pages.setCurrentIndex(0)
        self._show_step(self._first_incomplete_step())

    def _first_incomplete_step(self) -> int:
        if not self._city_is_valid():
            return 1
        status = self._current_setup_status()
        ready = (
            status.weather_key_saved,
            status.price_key_saved,
            status.tapo_saved,
        )
        if not any(ready) or all(ready):
            return 0
        return ready.index(False) + 1

    def _open_contribution_page(self) -> None:
        self._open_link(_CONTRIBUTE_URL)

    def _build_language_block(self, parent: QtWidgets.QWidget) -> QtWidgets.QWidget:
        box = QtWidgets.QWidget(parent)
        layout = QtWidgets.QVBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        form = QtWidgets.QFormLayout()
        self._language = QtWidgets.QComboBox(box)
        self._language.addItem("English", "en")
        self._language.addItem("Español", "es")
        self._language.setAccessibleName("Language")
        self._language_label = QtWidgets.QLabel("Language", box)
        self._language_label.setBuddy(self._language)
        form.addRow(self._language_label, self._language)
        layout.addLayout(form)

        self._spain_note = QtWidgets.QLabel(
            "Strom currently works in Spain. More countries are coming.", box
        )
        self._spain_note.setWordWrap(True)
        self._spain_note.setForegroundRole(QtGui.QPalette.ColorRole.PlaceholderText)
        layout.addWidget(self._spain_note)

        self._contribute_button = QtWidgets.QPushButton(
            "Contribute on GitHub", box
        )
        self._contribute_button.setObjectName("tertiaryLink")
        self._contribute_button.setFlat(True)
        self._contribute_button.setCursor(
            QtCore.Qt.CursorShape.PointingHandCursor
        )
        self._contribute_button.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Maximum,
            QtWidgets.QSizePolicy.Policy.Fixed,
        )
        self._contribute_button.setToolTip(
            "Open the Strom repository and help add support for your country."
        )
        self._contribute_button.clicked.connect(self._open_contribution_page)
        layout.addWidget(
            self._contribute_button,
            alignment=QtCore.Qt.AlignmentFlag.AlignLeft,
        )
        layout.addStretch(1)
        return box

    def _city_is_valid(self) -> bool:
        return city_is_valid(self._city.currentText())

    def _valid_location(self) -> bool:
        valid = self._city_is_valid()
        self._location_error.setText("" if valid else self._translated(
            "Enter a city or village in Spain without a country suffix."
        ))
        return valid

    def _update_location_note(self) -> None:
        if hasattr(self, "_location_note"):
            city = self._city.currentText().strip()
            template = self._translated("Using {city} weather and Spanish (ES) electricity prices.")
            self._location_note.setText(template.format(city=city))

    def _build_weather_block(
        self, parent: QtWidgets.QWidget
    ) -> QtWidgets.QWidget:
        box = QtWidgets.QWidget(parent)
        layout = QtWidgets.QVBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self._weather_help_text = _WEATHER_HELP_TEXT
        self._section_header(
            layout, "Connect OpenWeatherMap", self._weather_help_text,
            _WEATHER_SIGNUP_URL,
        )

        needs = QtWidgets.QLabel(
            "You'll need an OpenWeatherMap key, an ENTSO-E token, and your "
            "plug's IP address.",
            box,
        )
        needs.setWordWrap(True)
        needs.setForegroundRole(QtGui.QPalette.ColorRole.PlaceholderText)
        layout.addWidget(needs)

        form = QtWidgets.QFormLayout()
        form.setSpacing(8)
        self._city = QtWidgets.QComboBox(box)
        self._city.setEditable(True)
        self._city.setInsertPolicy(QtWidgets.QComboBox.InsertPolicy.NoInsert)
        self._city.addItems([
            "Barcelona", "Madrid", "Valencia", "Sevilla", "Zaragoza", "Málaga",
            "Murcia", "Palma", "Bilbao", "Alicante", "Córdoba", "Valladolid",
            "Vigo", "Gijón", "A Coruña", "Granada", "Pamplona", "Santander",
            "Toledo", "Cáceres", "Santiago de Compostela", "Las Palmas de Gran Canaria",
            "Santa Cruz de Tenerife", "Ceuta", "Melilla",
        ])
        self._city.setAccessibleName("City or village in Spain")
        city_editor = self._city.lineEdit()
        city_completer = self._city.completer()
        assert city_editor is not None and city_completer is not None
        city_editor.setMaxLength(120)
        city_completer.setCaseSensitivity(QtCore.Qt.CaseSensitivity.CaseInsensitive)
        form.addRow("City", self._city)
        self._city.currentTextChanged.connect(self._update_location_note)
        self._city.currentTextChanged.connect(self._refresh_setup_status)

        key_row = QtWidgets.QHBoxLayout()
        self._weather_key_edit = QtWidgets.QLineEdit(box)
        self._weather_key_edit.setAccessibleName("Weather API key")
        self._weather_key_edit.setEchoMode(QtWidgets.QLineEdit.EchoMode.Password)
        self._weather_key_edit.setPlaceholderText(
            "Paste your weather key here"
        )
        self._weather_key_edit.setToolTip(
            "Your key is hidden while typing; paste works normally."
        )
        key_row.addWidget(self._weather_key_edit, 1)
        self._weather_save = QtWidgets.QPushButton("Save", box)
        self._weather_save.clicked.connect(self._on_save_weather)
        key_row.addWidget(self._weather_save)
        self._weather_test = QtWidgets.QPushButton("Test", box)
        self._weather_test.setToolTip(
            "Ask OpenWeatherMap to check the key before you rely on it."
        )
        self._weather_test.clicked.connect(self._on_test_weather)
        key_row.addWidget(self._weather_test)
        form.addRow("Key", key_row)
        layout.addLayout(form)

        self._location_error = QtWidgets.QLabel("", box)
        self._location_error.setWordWrap(True)
        self._location_error.setProperty("statusKind", "error")
        repolish(self._location_error)
        layout.addWidget(self._location_error)

        self._weather_status = QtWidgets.QLabel("", box)
        self._weather_status.setWordWrap(True)
        layout.addWidget(self._weather_status)
        return box

    def _build_price_block(self, parent: QtWidgets.QWidget) -> QtWidgets.QWidget:
        box = QtWidgets.QWidget(parent)
        layout = QtWidgets.QVBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self._price_help_text = _PRICE_HELP_TEXT
        self._section_header(
            layout, "Connect ENTSO-E", self._price_help_text, _PRICE_SIGNUP_URL,
        )

        form = QtWidgets.QFormLayout()
        form.setSpacing(8)
        key_row = QtWidgets.QHBoxLayout()
        self._price_key_edit = QtWidgets.QLineEdit(box)
        self._price_key_edit.setAccessibleName("Electricity price API key")
        self._price_key_edit.setEchoMode(QtWidgets.QLineEdit.EchoMode.Password)
        self._price_key_edit.setPlaceholderText(
            "Paste your electricity price key here"
        )
        self._price_key_edit.setToolTip(
            "Your key is hidden while typing; paste works normally."
        )
        key_row.addWidget(self._price_key_edit, 1)
        self._price_save = QtWidgets.QPushButton("Save", box)
        self._price_save.clicked.connect(self._on_save_price)
        key_row.addWidget(self._price_save)
        self._price_test = QtWidgets.QPushButton("Test", box)
        self._price_test.setToolTip(
            "Ask ENTSO-E for recent prices to check the key."
        )
        self._price_test.clicked.connect(self._on_test_price)
        key_row.addWidget(self._price_test)
        form.addRow("Key", key_row)
        layout.addLayout(form)

        self._price_status = QtWidgets.QLabel("", box)
        self._price_status.setWordWrap(True)
        layout.addWidget(self._price_status)
        return box

    def _build_tapo_block(self, parent: QtWidgets.QWidget) -> QtWidgets.QWidget:
        box = QtWidgets.QWidget(parent)
        layout = QtWidgets.QVBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self._tapo_help_text = _TAPO_HELP_TEXT
        self._section_header(
            layout, "Smart plug account (Tapo)", self._tapo_help_text
        )

        hint = QtWidgets.QLabel(
            "Many plugs need no account. Enter the IP address and click Test.",
            box,
        )
        hint.setWordWrap(True)
        hint.setForegroundRole(QtGui.QPalette.ColorRole.PlaceholderText)
        layout.addWidget(hint)

        form = QtWidgets.QFormLayout()
        form.setSpacing(8)
        self._tapo_ip = QtWidgets.QLineEdit(box)
        self._tapo_ip.setAccessibleName("Plug IP address")
        self._tapo_ip.setPlaceholderText("Plug IP address, e.g. 192.168.1.42")
        self._tapo_ip.setToolTip(
            "The Tapo app shows it under the plug's device information."
        )
        form.addRow("IP address", self._tapo_ip)
        layout.addLayout(form)

        self._account_toggle = QtWidgets.QToolButton(box)
        self._account_toggle.setText("Use the TP-Link account")
        self._account_toggle.setCheckable(True)
        self._account_toggle.setAutoRaise(True)
        self._account_toggle.setArrowType(QtCore.Qt.ArrowType.RightArrow)
        self._account_toggle.setToolButtonStyle(
            QtCore.Qt.ToolButtonStyle.ToolButtonTextBesideIcon
        )
        self._account_toggle.toggled.connect(self._on_account_toggled)
        layout.addWidget(self._account_toggle)

        self._account_fields = QtWidgets.QWidget(box)
        account_layout = QtWidgets.QVBoxLayout(self._account_fields)
        account_layout.setContentsMargins(14, 0, 0, 0)
        account_layout.setSpacing(8)
        self._account_explanation = QtWidgets.QLabel(
            "Only needed if the plug asks for it. Strom sends these to the "
            "plug on your local network, never to TP-Link, and does not keep "
            "the password: a successful Test stores a derived key instead.",
            self._account_fields,
        )
        self._account_explanation.setWordWrap(True)
        self._account_explanation.setForegroundRole(
            QtGui.QPalette.ColorRole.PlaceholderText
        )
        account_layout.addWidget(self._account_explanation)
        account_form = QtWidgets.QFormLayout()
        account_form.setSpacing(8)
        self._tapo_email = QtWidgets.QLineEdit(self._account_fields)
        self._tapo_email.setAccessibleName("Plug account email")
        account_form.addRow("Email", self._tapo_email)
        self._tapo_password = QtWidgets.QLineEdit(self._account_fields)
        self._tapo_password.setAccessibleName("Plug account password")
        self._tapo_password.setEchoMode(QtWidgets.QLineEdit.EchoMode.Password)
        account_form.addRow("Password", self._tapo_password)
        account_layout.addLayout(account_form)
        self._account_fields.hide()
        layout.addWidget(self._account_fields)

        buttons = QtWidgets.QHBoxLayout()
        buttons.addStretch(1)
        self._tapo_save = QtWidgets.QPushButton("Save", box)
        self._tapo_save.setToolTip(
            "Save the plug address. The account details are checked by Test "
            "and never stored."
        )
        self._tapo_save.clicked.connect(self._on_save_tapo)
        buttons.addWidget(self._tapo_save)
        self._tapo_test = QtWidgets.QPushButton("Test", box)
        self._tapo_test.setToolTip(
            "Try to reach the plug on your network with these details."
        )
        self._tapo_test.clicked.connect(self._on_test_tapo)
        buttons.addWidget(self._tapo_test)
        layout.addLayout(buttons)

        self._tapo_status = QtWidgets.QLabel("", box)
        self._tapo_status.setWordWrap(True)
        layout.addWidget(self._tapo_status)
        return box

    def _on_account_toggled(self, checked: bool) -> None:
        self._account_fields.setVisible(checked)
        self._account_toggle.setArrowType(
            QtCore.Qt.ArrowType.DownArrow
            if checked
            else QtCore.Qt.ArrowType.RightArrow
        )
        if checked:
            self._tapo_email.setFocus()

    def _section_header(
        self,
        layout: QtWidgets.QVBoxLayout,
        title: str,
        help_text: str,
        url: str | None = None,
    ) -> None:
        row = QtWidgets.QHBoxLayout()
        heading = QtWidgets.QLabel(title)
        heading.setObjectName("sectionTitle")
        font = heading.font()
        font.setBold(True)
        heading.setFont(font)
        row.addWidget(heading)
        row.addStretch(1)
        button = QtWidgets.QPushButton("How do I get this?")
        button.setFlat(True)
        button.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        button.clicked.connect(
            lambda checked=False: self._show_help(help_text, url)
        )
        row.addWidget(button)
        layout.addLayout(row)

    @staticmethod
    def _empty_status() -> SetupStatus:
        return SetupStatus(
            weather_key_saved=False,
            price_key_saved=False,
            tapo_saved=False,
        )

    def _current_setup_status(self) -> SetupStatus:
        raw = self._config_dir_edit.text().strip()
        if not raw:
            return self._empty_status()
        try:
            return read_setup_status(Path(raw).expanduser())
        except OSError:
            return self._empty_status()

    def _missing_setup_items(self) -> list[str]:
        status = self._current_setup_status()
        missing = []
        if not status.weather_key_saved:
            missing.append("weather key")
        if not status.price_key_saved:
            missing.append("electricity price key")
        if not status.tapo_saved:
            missing.append("smart plug account")
        return missing

    def _refresh_setup_status(self) -> None:
        raw = self._config_dir_edit.text().strip()
        shown = raw if raw else self._translated("(none chosen)")
        self._settings_folder_label.setText(
            self._translated("Settings folder: {path}").format(path=shown)
        )
        if not raw:
            self._checklist_label.setText(self._translated("Choose a settings folder to begin."))
        elif self._missing_setup_items():
            self._checklist_label.setText(self._translated("Not ready yet."))
        else:
            self._checklist_label.setText(
                self._translated("All set. Start heating when you like.")
            )
        status = self._current_setup_status()
        for chip, done in (
            (self._weather_status, status.weather_key_saved),
            (self._price_status, status.price_key_saved),
        ):
            self._set_chip(
                chip,
                self._translated("Saved" if done else "Not set yet"),
            )
        if status.tapo_saved:
            tapo_text = "Saved"
        elif status.tapo_ip_saved:
            tapo_text = "Not verified yet"
        else:
            tapo_text = "Not set yet"
        self._set_chip(self._tapo_status, self._translated(tapo_text))
        self._update_heating_chips(status)
        self._sync_step_indicator()
        self._refresh_controls()

    def _update_heating_chips(self, status: SetupStatus) -> None:
        if status.tapo_saved:
            plug_text = "Plug account ✓"
        elif status.tapo_ip_saved:
            plug_text = "Plug not verified"
        else:
            plug_text = "Plug account missing"
        chips = (
            (self._chip_weather, status.weather_key_saved,
             "Weather key ✓", "Weather key missing"),
            (self._chip_price, status.price_key_saved,
             "Price key ✓", "Price key missing"),
        )
        for chip, done, ready_text, missing_text in chips:
            chip.setText(
                self._translated(ready_text if done else missing_text)
            )
            chip.setProperty("statusKind", "ready" if done else "missing")
            repolish(chip)
        self._chip_plug.setText(self._translated(plug_text))
        self._chip_plug.setProperty(
            "statusKind", "ready" if status.tapo_saved else "missing"
        )
        repolish(self._chip_plug)

    def _sync_step_indicator(self) -> None:
        """Color the stepper: the current step stands out, done steps tick."""
        status = self._current_setup_status()
        done = (
            True,  # the language always has a value
            self._city_is_valid() and status.weather_key_saved,
            status.price_key_saved,
            status.tapo_saved,
        )
        current = self._account_pages.currentIndex()
        for index, (name, complete) in enumerate(zip(_STEP_SHORT_NAMES, done)):
            item = self._step_list.item(index)
            text = f"{index + 1} {self._translated(name)}"
            if complete and index != current:
                item.setText(f"✓ {text}")
            else:
                item.setText(text)
        blocker = QtCore.QSignalBlocker(self._step_list)
        self._step_list.setCurrentRow(current)
        del blocker

    def _set_chip(
        self, chip: QtWidgets.QLabel, text: str, *, error: bool = False
    ) -> None:
        chip.setText(text)
        if error:
            status_kind = "error"
        elif text == self._translated("Saved"):
            status_kind = "ready"
        else:
            status_kind = "missing"
        chip.setProperty("statusKind", status_kind)
        repolish(chip)

    def _setup_error_text(self, exc: SetupError) -> str:
        """Translate a setup validation message, including its values."""
        if exc.code == "bad_ip":
            template = (
                "'{value}' does not look like an IP address. "
                "The Tapo app shows it under the plug's device information."
            )
            return self._translated(template).format(**exc.params)
        return self._translated(str(exc))

    def _prepared_dir_for_save(self, chip: QtWidgets.QLabel) -> Path | None:
        return self._prepared_config_dir(
            lambda text: self._set_chip(chip, text, error=True)
        )

    def _on_save_weather(self) -> bool:
        chip = self._weather_status
        config_dir = self._prepared_dir_for_save(chip)
        if config_dir is None:
            return False
        try:
            path = save_api_key(
                config_dir, WEATHER_FILE, self._weather_key_edit.text(),
                "weather key",
            )
        except SetupError as exc:
            self._set_chip(chip, self._setup_error_text(exc), error=True)
            return False
        except OSError as exc:
            self._set_chip(
                chip,
                self._translated(
                    "Could not save the weather key: {error}"
                ).format(error=exc),
                error=True,
            )
            return False
        self._weather_key_edit.clear()
        self._set_chip(chip, self._translated("Saved"))
        self._append_log(
            self._translated("Weather key saved to {path}").format(path=path)
        )
        self._refresh_setup_status()
        return True

    def _on_save_price(self) -> bool:
        chip = self._price_status
        config_dir = self._prepared_dir_for_save(chip)
        if config_dir is None:
            return False
        try:
            path = save_api_key(
                config_dir, PRICE_FILE, self._price_key_edit.text(),
                "electricity price key",
            )
        except SetupError as exc:
            self._set_chip(chip, self._setup_error_text(exc), error=True)
            return False
        except OSError as exc:
            self._set_chip(
                chip,
                self._translated(
                    "Could not save the price key: {error}"
                ).format(error=exc),
                error=True,
            )
            return False
        self._price_key_edit.clear()
        self._set_chip(chip, self._translated("Saved"))
        self._append_log(
            self._translated("Electricity price key saved to {path}").format(
                path=path
            )
        )
        self._refresh_setup_status()
        return True

    def _on_save_tapo(self) -> bool:
        chip = self._tapo_status
        config_dir = self._prepared_dir_for_save(chip)
        if config_dir is None:
            return False
        stored = read_tapo_credentials(config_dir)
        device_ip = self._tapo_ip.text().strip() or (
            stored.device_ip if stored else ""
        )
        # The account is verified by Test, never written: a successful Test
        # stores the derived proof and drops the password. Saving the
        # address keeps the credentials already in the file.
        try:
            path = save_tapo_credentials(
                config_dir,
                device_ip,
                email=(stored.email if stored else ""),
                password=(stored.password if stored else ""),
                plug_config=(stored.plug_config if stored else ""),
            )
        except SetupError as exc:
            self._set_chip(chip, self._setup_error_text(exc), error=True)
            return False
        except OSError as exc:
            self._set_chip(
                chip,
                self._translated(
                    "Could not save the plug details: {error}"
                ).format(error=exc),
                error=True,
            )
            return False
        self._tapo_ip.clear()
        self._append_log(
            self._translated("Plug address saved to {path}").format(path=path)
        )
        self._refresh_setup_status()
        return True

    def _saved_key(self, file_name: str, env_var: str) -> str | None:
        """The environment key when set, else the saved file, else None."""
        value = os.getenv(env_var, "").strip()
        if value:
            return value
        raw = self._config_dir_edit.text().strip()
        if not raw:
            return None
        try:
            content = (
                Path(raw).expanduser() / file_name
            ).read_text(encoding="utf-8").strip()
        except (OSError, UnicodeDecodeError):
            return None
        return content or None

    def _on_test_weather(self) -> None:
        key = self._weather_key_edit.text().strip() or self._saved_key(
            WEATHER_FILE, "WEATHER_API_KEY"
        )
        if not key:
            self._set_chip(
                self._weather_status,
                self._translated("Paste the key first, then test it."),
                error=True,
            )
            return
        city = self._city.currentText().strip()
        self._weather_test.setEnabled(False)
        self._set_chip(self._weather_status, self._translated("Testing…"))
        self._checker.check_weather(key, (city + ", ES") if city else "Barcelona, ES")

    def _on_weather_checked(self, ok: bool, message: str) -> None:
        self._weather_test.setEnabled(True)
        if ok:
            self._set_chip(self._weather_status, self._translated("Works ✓"))
        else:
            self._set_chip(self._weather_status, message, error=True)

    def _on_test_price(self) -> None:
        key = self._price_key_edit.text().strip() or self._saved_key(
            PRICE_FILE, "PRICE_API_KEY"
        )
        if not key:
            self._set_chip(
                self._price_status,
                self._translated("Paste the key first, then test it."),
                error=True,
            )
            return
        self._price_test.setEnabled(False)
        self._set_chip(self._price_status, self._translated("Testing…"))
        self._checker.check_price(key)

    def _on_price_checked(self, ok: bool, message: str) -> None:
        self._price_test.setEnabled(True)
        if ok:
            self._set_chip(self._price_status, self._translated("Works ✓"))
        else:
            self._set_chip(self._price_status, message, error=True)

    def _plug_credentials_for_test(self) -> PlugCredentials | None:
        """Build the test credentials: typed values, then stored, then env."""
        raw = self._config_dir_edit.text().strip()
        stored = read_tapo_credentials(Path(raw).expanduser()) if raw else None
        device_ip = (
            self._tapo_ip.text().strip()
            or (stored.device_ip if stored else "")
            or os.getenv("DEVICEIP", "").strip()
        )
        if not device_ip:
            return None
        email = self._tapo_email.text().strip()
        password = self._tapo_password.text().strip()
        if email and password:
            return PlugCredentials(
                device_ip=device_ip, email=email, password=password
            )
        if stored and stored.plug_config:
            return PlugCredentials(
                device_ip=device_ip, plug_config=stored.plug_config
            )
        if stored and stored.email and stored.password:
            return PlugCredentials(
                device_ip=device_ip,
                email=stored.email,
                password=stored.password,
            )
        env_email = os.getenv("EMAIL", "").strip()
        env_password = os.getenv("PASSWORD", "").strip()
        if env_email and env_password:
            return PlugCredentials(
                device_ip=device_ip, email=env_email, password=env_password
            )
        return PlugCredentials(device_ip=device_ip)

    def _on_test_tapo(self) -> None:
        credentials = self._plug_credentials_for_test()
        if credentials is None:
            self._set_chip(
                self._tapo_status,
                self._translated("Enter the plug IP address first."),
                error=True,
            )
            return
        self._tested_plug = credentials
        self._tapo_test.setEnabled(False)
        self._set_chip(self._tapo_status, self._translated("Testing…"))
        self._checker.check_plug(credentials)

    def _on_plug_checked(
        self, ok: bool, message: str, plug_config: str
    ) -> None:
        self._tapo_test.setEnabled(True)
        if not ok:
            self._set_chip(
                self._tapo_status, self._translated(message), error=True
            )
            return
        # Reaching the plug and storing the proof are separate outcomes: a
        # failed save keeps its own error instead of the success chip.
        if plug_config and not self._persist_plug_config(plug_config):
            return
        self._set_chip(self._tapo_status, self._translated("Works ✓"))

    def _persist_plug_config(self, plug_config: str) -> bool:
        """Store the derived proof so the account is no longer needed."""
        credentials = self._tested_plug
        if credentials is None or not credentials.device_ip:
            return True
        config_dir = self._prepared_dir_for_save(self._tapo_status)
        if config_dir is None:
            return False
        try:
            save_tapo_credentials(
                config_dir,
                credentials.device_ip,
                plug_config=plug_config,
            )
        except SetupError as exc:
            self._set_chip(
                self._tapo_status, self._setup_error_text(exc), error=True
            )
            return False
        except OSError as exc:
            self._set_chip(
                self._tapo_status,
                self._translated(
                    "Could not save the plug details: {error}"
                ).format(error=exc),
                error=True,
            )
            return False
        self._tapo_email.clear()
        self._tapo_password.clear()
        self._refresh_setup_status()
        return True

    def _show_help(self, text: str, url: str | None = None) -> None:
        """Static guidance with an optional button for the sign-up page."""
        box = QtWidgets.QMessageBox(self)
        box.setWindowTitle(self._translated("Setup help"))
        box.setTextFormat(QtCore.Qt.TextFormat.RichText)
        box.setText(self._translated(text))
        if url:
            open_button = box.addButton(
                self._translated("Open the sign-up page"),
                QtWidgets.QMessageBox.ButtonRole.ActionRole
            )
            open_button.clicked.connect(
                lambda checked=False: self._open_link(url)
            )
        ok_button = box.addButton(
            "OK", QtWidgets.QMessageBox.ButtonRole.AcceptRole
        )
        box.setDefaultButton(ok_button)
        box.exec()
