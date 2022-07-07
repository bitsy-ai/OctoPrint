import socket
from flask_babel import gettext
import octoprint
from octoprint.webcams import WebcamConfiguration


class JanusWebcamPlugin(
    octoprint.plugin.AssetPlugin,
    octoprint.plugin.TemplatePlugin,
    octoprint.plugin.SettingsPlugin,
    octoprint.plugin.WebcamPlugin,
):
    def get_assets(self):
        return {
            "js": [
                "js/januswebcam.js",
                "js/januswebcam_settings.js",
                "js/janus.js",
                "js/webrtc-adaptor.js",
            ],
            "less": ["less/januswebcam.less"],
            "css": ["css/januswebcam.css"],
        }

    def get_template_configs(self):
        return [
            {
                "type": "settings",
                "template": "januswebcam_settings.jinja2",
                "custom_bindings": True,
            },
            {
                "type": "webcam",
                "name": "Janus Webcam",
                "template": "januswebcam_webcam.jinja2",
                "custom_bindings": True,
                "suffix": "_real",
            },
        ]

    def get_webcam_configurations(self):
        return [
            WebcamConfiguration(
                name="janus",
                display_name="Janus WebRTC Webcam",
                flip_h=self._settings.get(["flipH"]),
                flip_v=self._settings.get(["flipV"]),
                rotate_90=self._settings.get(["rotate90"]),
                snapshot="",
                attachments=dict(
                    janus_api_url=self._settings.get(["janusApiUrl"]),
                    janus_api_token=self._settings.get(["janusApiToken"]),
                    stream_webrtc_ice_servers=self._settings.get(
                        ["streamWebrtcIceServers"]
                    ),
                    janus_selected_stream_id=self._settings.get(["selectedStreamId"]),
                    janus_bitrate_update_interval=self._settings.get(
                        ["janusBitrateInterval"]
                    ),
                ),
            )
        ]

    def get_settings_defaults(self):
        janusApiUrl = "http://{}:8088/janus".format(socket.gethostname())
        return dict(
            flipH=False,
            flipV=False,
            rotate90=False,
            janusApiUrl=janusApiUrl,
            janusApiToken=None,
            janusBitrateInterval=1000,
            selectedStreamId=None,
            streamWebrtcIceServers="stun:stun.l.google.com:19302",
        )

    def get_settings_version(self):
        return 1


__plugin_name__ = gettext("Janus Webcam")
__plugin_author__ = "Leigh Johnson"
__plugin_description__ = "Provides a WebRTC video stream viewer in OctoPrint's UI, video stream provided by Janus Gateway's Streaming Plugin API"
__plugin_license__ = "AGPLv3"
__plugin_pythoncompat__ = ">=3.7,<4"
__plugin_implementation__ = JanusWebcamPlugin()
