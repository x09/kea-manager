Name:          kea-manager
Version:       1.0
Release:       alt1.git6f34e67
License:       %gpl3only
Group:         System/Configuration/Other
Source:        %name-v%version.tgz
BuildArch:     noarch

Summary:       Graphical management utility for KEA DHCP
Url:           https://github.com/x09/kea-manager

BuildRequires: 	rpm-build-licenses

Requires: 	python3-modules-tkinter
Requires:       python3-module-matplotlib
Requires: 	python3

%add_python3_path %_datadir/%name

%description
A graphical management utility for GNU/Linux, similar to Microsoft DHCP Manager.
For managing KEA-DHCP 3.2.x and above, using API or local config file operations.

%description -l ru_RU.UTF-8
Графическая утилита для GNU/Linux — аналог Microsoft DHCP Manager.
Для управления KEA-DHCP 3.2.x и выше, используя API или работу с локальными файлами.

%prep
%setup -n %name-v%version

%install
for language in en; do
	mkdir -p %buildroot/%_datadir/locale/$language/LC_MESSAGES/
	install -m644 kea_manager/locale/$language/LC_MESSAGES/kea-manager.mo %buildroot/%_datadir/locale/$language/LC_MESSAGES/
done

mkdir -p %buildroot/%_datadir/%name/kea_manager/{ui,util,model,tools}

cp -r kea_manager/ui/* %buildroot/%_datadir/%name/kea_manager/ui/
cp -r kea_manager/util/* %buildroot/%_datadir/%name/kea_manager/util/
cp -r kea_manager/model/* %buildroot/%_datadir/%name/kea_manager/model/

cp kea_manager/*.py %buildroot/%_datadir/%name/kea_manager/
cp tools/gen-tls-certs.sh %buildroot/%_datadir/%name/kea_manager/tools/

mkdir -p  %buildroot/%_desktopdir
cp %name.desktop %buildroot/%_desktopdir/%name.desktop

mkdir -p  %buildroot/%_iconsdir
for s in 32 64 128 256; do
    mkdir -p %buildroot/%_iconsdir/hicolor/${s}x${s}/apps/
    cp icons/%name-${s}.png %buildroot/%_iconsdir/hicolor/${s}x${s}/apps/%name.png
done

mkdir -p %buildroot/%_bindir/
cp %name.py %buildroot/%_bindir/kea-manager
chmod 755 %buildroot/%_bindir/kea-manager

%post

%postun

%files
%_bindir/kea-manager
%_iconsdir/hicolor/*
%_desktopdir/%name.desktop
%_datadir/%name/kea_manager/*
%_datadir/locale/en/LC_MESSAGES/*


%changelog
* Wed Aug 12 2026 Anton Shevtsov <shevtsov.anton@gmail.com> 1.0-alt1.git6f34e67
- Add monitoring feature (python3-module-matplotlib requires)

* Wed Aug 12 2026 Anton Shevtsov <shevtsov.anton@gmail.com> 1.0-alt1.git09fc927
- 09fc927 build 

* Wed Aug 05 2026 Anton Shevtsov <shevtsov.anton@gmail.com> 1.0-alt1
- First version
