"""Human-readable channel labels kept only on the Python host."""
from .channel_settings import ChannelSettingsStore


def channel_label(value):
    if not isinstance(value, str):
        raise ValueError('Label must be text; use an empty string to clear it')
    value = value.strip()
    if len(value) > 80 or (value and not value.isprintable()):
        raise ValueError('Label must be at most 80 characters on one line')
    return value or None


class LabelStore(ChannelSettingsStore):
    filename = 'labels.local.json'
    setting_name = 'label'

    def validate(self, value):
        return channel_label(value)


class ChannelLabelMixin:
    def get_label(self, channel):
        """Return the saved label, or an empty string when no label is set."""
        return self._label_store.get(*self._channel_key(channel)) or ''

    def set_label(self, channel, label):
        """Save a label without instrument I/O. Empty text restores DAC N in the UI."""
        address, local = self._channel_key(channel)
        return self._label_store.set(address, local, channel_label(label)) or ''
