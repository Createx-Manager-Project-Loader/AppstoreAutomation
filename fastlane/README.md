fastlane documentation
----

# Installation

Make sure you have the latest version of the Xcode command line tools installed:

```sh
xcode-select --install
```

For _fastlane_ installation instructions, see [Installing _fastlane_](https://docs.fastlane.tools/#installing-fastlane)

# Available Actions

## iOS

### ios update_whats_new

```sh
[bundle exec] fastlane ios update_whats_new
```

Update What's New text in App Store Connect

### ios first_release

```sh
[bundle exec] fastlane ios first_release
```

First release: full metadata for an app that is not in the store yet

### ios upload_metadata

```sh
[bundle exec] fastlane ios upload_metadata
```

Upload App Store Connect metadata and screenshots

### ios upload_metadata_for_locale

```sh
[bundle exec] fastlane ios upload_metadata_for_locale
```

Upload App Store Connect metadata for one locale

### ios upload_app_info_for_locale

```sh
[bundle exec] fastlane ios upload_app_info_for_locale
```

Upload app name and subtitle for one locale

### ios upload_app_subtitle_for_locale

```sh
[bundle exec] fastlane ios upload_app_subtitle_for_locale
```

Upload app subtitle for one locale

### ios update_whats_new_for_locale

```sh
[bundle exec] fastlane ios update_whats_new_for_locale
```

Update What's New text in App Store Connect for one locale

----

This README.md is auto-generated and will be re-generated every time [_fastlane_](https://fastlane.tools) is run.

More information about _fastlane_ can be found on [fastlane.tools](https://fastlane.tools).

The documentation of _fastlane_ can be found on [docs.fastlane.tools](https://docs.fastlane.tools).
