// var opaqueId = "streamingtest-" + Janus.randomString(12);

// var remoteTracks = {}, remoteVideos = 0, dataMid = null;
// var bitrateTimer = {};
// var spinner = {};

// var simulcastStarted = {}, svcStarted = {};

// var streamsList = {};
// var selectedStream = null;

// Helper to escape XML tags
function escapeXmlTags(value) {
  if (value) {
    var escapedValue = value.replace(new RegExp('<', 'g'), '&lt');
    escapedValue = escapedValue.replace(new RegExp('>', 'g'), '&gt');
    return escapedValue;
  }
}

$(function () {
  function JanusWebcamViewModel(parameters) {
    var self = this;
    self.loginState = parameters[0];
    self.settings = parameters[1];

    self.loading = ko.observable(false);
    self.active = ko.observable(false);
    self.ready = ko.observable(false);

    self.webcamDisableTimeout = undefined;
    self.webcamLoaded = ko.observable(false);
    self.webcamError = ko.observable(false);
    self.webcamSlowLink = ko.observable(false);
    self.webcamMuted = ko.observable(true);
    self.webRTCPeerConnection = null;
    self.webcamElement = null;


    self.janus = null;
    self.janusStreamingPlugin = null;
    self.videoLoading = ko.observable(false);

    self.streams = ko.observableArray();
    self.selectedStreamId = ko.observable();

    self.remoteTracks = {};
    self.bitrateTimer = {};
    self.bitrateText = ko.observable();

    self.showStartButton = ko.pureComputed(function () {
      return self.ready() && !self.active();
    });

    self.showVideo = ko.observable(false);

    self.onBeforeBinding = function () {
      self.janusBitrateInterval = self.settings.settings.plugins.januswebcam.janusBitrateInterval;
      self.janusApiUrl = self.settings.settings.plugins.januswebcam.janusApiUrl;
      self.janusApiToken = self.settings.settings.plugins.januswebcam.janusApiToken;
      self.webcamEnabled = self.settings.settings.webcam.webcamEnabled;
      self.streamWebrtcIceServers = self.settings.settings.streamWebrtcIceServers;
      self.selectedStreamId(self.settings.settings.plugins.januswebcam.selectedStreamId);
      self.selectedStreamId.subscribe(function (newValue) {
        if (newValue == undefined) {
          return self.ready(false);
        }
        return self.ready(true);
      })
    };

    self.onEventSettingsUpdated = function (payload) {
      // the webcam url might have changed, make sure we replace it now if the
      // tab is focused
      // TODO
    };

    self._getActiveWebcamVideoElement = function () {
      return self.webcamElement
    };

    self.launchWebcamPictureInPicture = function () {
      self._getActiveWebcamVideoElement().requestPictureInPicture();
    };

    self.launchWebcamFullscreen = function () {
      self._getActiveWebcamVideoElement().requestFullscreen();
    };

    self._disableWebcam = function () {

    };

    self.start = function () {
      if (
        !OctoPrint.coreui.browserTabVisible
      ) {
        return;
      }

      if (self.webcamDisableTimeout != undefined) {
        clearTimeout(self.webcamDisableTimeout);
      }

      // IF disabled then we dont need to do anything
      if (self.settings.webcamEnabled() == false) {
        console.log("Webcam not enabled");
        return;
      }
    };

    self.onWebcamLoaded = function () {
      if (self.webcamLoaded()) return;

      log.debug("Webcam stream loaded");
      self.webcamLoaded(true);
      self.webcamError(false);
    };

    self.onWebcamErrored = function () {
      log.debug("Webcam stream failed to load/disabled");
      self.webcamLoaded(false);
      self.webcamError(true);
    };

    self.onTabChange = function (current, previous) {
      if (current == "#control") {
        self._enableWebcam();
      } else if (previous == "#control") {
        self._disableWebcam();
      }
    };

    self.onBrowserTabVisibilityChange = function (status) {
      if (status) {
        self._enableWebcam();
      } else {
        self._disableWebcam();
      }
    };

    self.onUserPermissionsChanged =
      self.onUserLoggedIn =
      self.onUserLoggedOut =
      function () {
        self.syncWebcamElements();
      };

    self.onAllBound = function (allViewModels) {
      self.videoContainer = $("#janus_webcam_videos");
      self.initJanus();
    };

    self.syncWebcamElements = function () {
      self.webcamElement = document.getElementById("janus_webcam");
    };

    self.onStartup = function () {
      self.syncWebcamElements();
    };

    self.updateStreamsList = function () {
      self.loading(true);
      var body = { request: "list" };
      console.log("Sending msg to Janus API:", body);
      self.janusStreamingPlugin.send({
        message: body,
        success: function (result) {
          console.log("Janus stream list: ", result);
          setTimeout(function () {
            self.loading(false);
          }, 500);
          if (!result) {
            let msg = "Received no response to query for available WebRTC streams"
            console.error(msg);
            return;
          }
          if (result["list"]) {
            self.streams(result["list"]);
          }
        }
      });
    }

    self.onJanusConnectSuccess = function (pluginHandle) {
      self.janusStreamingPlugin = pluginHandle;
      let msg = "Janus Gateway plugin attached " + self.janusStreamingPlugin.getPlugin() + ", id=" + self.janusStreamingPlugin.getId();
      console.log(msg);
      self.updateStreamsList();
    }

    self.onJanusError = function (error) {
      let msg = "Error attaching Janus WebRTC plugin... " + error;
      console.error(msg);
      self.webcamError(true);
    }

    self.onJanusIceSate = function (state) {
      let msg = "ICE state changed to " + state;
      console.log(msg);
    }

    self.onJanusWebrtcState = function (state) {
      let msg = "WebRTC PeerConnection state changed to " + state;
      console.log(msg)
    }

    self.onSlowLink = function (uplink, lost, mid) {
      let msg = "Janus Gateway reports connection problems " + (uplink ? "sending" : "receiving") +
        " packets on mid " + mid + " (" + lost + " lost packets)";
      console.warn(msg)
      self.webcamSlowLink(true);
    }

    // handle generic starting / started / stopped messages from Janus Gateway
    self.onJanusStatusChanged = function (msg) {
      var result = msg["result"];
      var status = result["status"];
      if (status === 'starting') {
        self.loading(true);
        self.active(true);
      }
      else if (status === 'started') {
        self.loading(false);
        self.active(true);
      }
      else if (status === 'stopped') {
        self.stopStream();
      } else {
        console.warn("Unhandled Janus status: ", status);
      }
    }

    // handle messages from Janus Gateway's streaming plugin
    self.onJanusStreamingEvent = function (msg) {
      // extract media id from eve
      var mid = result["mid"] ? result["mid"] : "0";
      // Is simulcast in place?
      var substream = result["substream"];
      var temporal = result["temporal"];
    }


    // handle janus jsep offer, create answer
    self.onJanusJSEP = function (jsep) {
      console.info("Handling SDP: ", jsep);
      var stereo = (jsep.sdp.indexOf("stereo=1") !== -1);
      self.janusStreamingPlugin.createAnswer(
        {
          jsep: jsep,
          // We want recvonly audio/video and, if negotiated, datachannels
          media: { audioSend: false, videoSend: false, data: true },
          customizeSdp: function (jsep) {
            if (stereo && jsep.sdp.indexOf("stereo=1") == -1) {
              // Make sure that our offer contains stereo too
              jsep.sdp = jsep.sdp.replace("useinbandfec=1", "useinbandfec=1;stereo=1");
            }
          },
          success: function (jsep) {
            console.debug("Got SDP!", jsep);
            // send a start WebRTC request with SDP
            var body = { request: "start" };
            self.janusStreamingPlugin.send({ message: body, jsep: jsep });
          },
          error: function (error) {
            let msg = "WebRTC error:" + error.message;
            self.onJanusError(msg);
          }
        });
    }

    self.onJanusMessage = function (msg, jsep) {
      console.log("Received Janus msg: ", msg);

      // handle async result from prior request or errors
      if (msg["result"]) {
        var result = msg["result"];
        if (result["status"]) {
          self.onJanusStatusChanged(msg);
        }
      } else if (msg["error"]) {
        self.onJanusError(msg);
        self.stopStream();
        return
      }

      // handle SDP offer
      if (jsep) {
        self.onJanusJSEP(jsep);
      }
    }

    // handle remote track received via WebRTC
    self.onJanusRemoteTrack = function (track, mid, on) {
      console.debug("Remote track (mid=" + mid + ") " + (on ? "added" : "removed") + ":", track);
      // handle track removed
      if (!on) {
        // Track removed, get rid of the stream and the rendering
        var stream = self.remoteTracks[mid];
        if (stream) {
          try {
            var tracks = stream.getTracks();
            for (var i in tracks) {
              var mst = tracks[i];
              if (mst)
                mst.stop();
            }
          } catch (e) { console.error("Unexpected error cleaning up remote tracks: ", e) }
        }
        delete self.remoteTracks[mid];
        return;
      }
      // If we're here, a new track was added
      var stream = null;
      var videoElId = null;
      if (track.kind === "audio") {
        console.warn("Audio tracks are not yet implemented by Janus OctoPrint plugin, ignoring");
      } else {
        // new video track: create a media stream from track data
        stream = new MediaStream();
        stream.addTrack(track.clone());
        self.remoteTracks[mid] = stream;
        console.log("Created remote video stream:", stream);

        // insert video element into DOM
        videoElId = 'janus_webcam_video_' + mid;
        $('#janus_webcam_videos').append('<video style="width: 100%" id="' + videoElId + '" playsinline/>');

        // Use a custom timer for this stream
        if (!self.bitrateTimer[mid]) {
          self.bitrateTimer[mid] = setInterval(function () {
            // Display updated bitrate, if supported
            var bitrate = self.janusStreamingPlugin.getBitrate(mid);
            self.bitrateText(bitrate);
          }, self.janusBitrateInterval);
        }
      }

      // attach MediaStream to video element
      Janus.attachMediaStream($('#' + videoElId).get(0), stream);

      // bind spinner state update to "playing" event
      $('#' + videoElId).bind("playing", function (ev) {
        self.videoLoading(false);
      });

      // trigger "playing" event
      $('#' + videoElId).get(0).play();
    }

    self.onJanusDataOpen = function (_data) {
      console.log("Janus data channel is available");
    }

    self.onJanusData = function (data) {
      console.debug("Janus data channel recv: ", data);
    }

    self.onJanusCleanup = function () {
      console.log("Janus received cleanup notification");
      $("janus_webcam_videos").empty();

      for (var i in self.bitrateTimer) {
        clearInterval(self.bitrateTimer[i]);
      }
      self.bitrateTimer = {};
      self.remoteTracks = {};
    }

    self.onJanusPluginAttach = function () {
      let opaqueId = Janus.randomString(12);
      return self.janus.attach({
        opaqueId: opaqueId,
        plugin: "janus.plugin.streaming",
        error: self.onJanusError,
        iceState: self.onJanusIceSate,
        onmessage: self.onJanusMessage,
        onremotetrack: self.onJanusRemoteTrack,
        ondataopen: self.onJanusDataOpen,
        ondata: self.onJanusData,
        slowLink: self.onSlowLink,
        success: self.onJanusConnectSuccess,
        webrtcState: self.onJanusWebrtcState,
      })
    }


    self.onJanusDestroyed = function () {
      console.warn("Janus session was destroyed!")
    }
    self._initJanusCallback = function () {
      // Make sure the browser supports WebRTC
      if (!Janus.isWebrtcSupported()) {
        let msg = "No WebRTC support detected."
        console.error(msg);
        self.webcamError(true);
        return;
      }
      var janusCfg = {
        server: self.settings.settings.plugins.januswebcam.janusApiUrl(),
        iceServers: [{ urls: self.settings.settings.plugins.januswebcam.streamWebrtcIceServers() }],
        success: self.onJanusPluginAttach,
        error: self.onJanusError,
        destroyed: self.onJanusDestroyed
      };

      if (self.settings.settings.plugins.januswebcam.janusApiToken() !== null) {
        janusCfg.token = self.settings.settings.plugins.januswebcam.janusApiToken();
      } else {
        console.warn("Janus Gateway API token is not set!");
      }
      self.janus = new Janus(janusCfg);
    }

    self.startStream = function () {
      if (self.selectedStreamId() == undefined) {
        console.warn("No Janus Gateway stream selected, refusing to start");
        return
      }
      // Send a request for more info on the selected streaming mountpoint
      self.loading(true);
      var body = { request: "info", id: self.selectedStreamId() };
      console.log("Requesting start Janus mountpoint: ", body);

      // display stream metadata (if metadata is provided)
      self.janusStreamingPlugin.send({
        message: body,
        success: function (result) {
          console.log("Received Janus stream info: ", result);
          if (result && result.info && result.info.metadata) {
            $('#janus_stream_metadata').html(escapeXmlTags(result.info.metadata));
          }
        }
      });

      // Send a request to watch stream
      var body = { request: "watch", id: self.selectedStreamId() };
      self.janusStreamingPlugin.send({ message: body });
    }

    self.stopStream = function () {
      var body = { request: "stop" };
      console.log("Sending stop request to Janus streaming plugin");
      self.janusStreamingPlugin.send({ message: body });
      self.janusStreamingPlugin.hangup();
    }

    self._enableWebcam = function () {
    }

    self.initJanus = function () {
      Janus.init({
        debug: "all",
        callback: self._initJanusCallback
      })
    }
  }


  OCTOPRINT_VIEWMODELS.push({
    construct: JanusWebcamViewModel,
    dependencies: [
      "loginStateViewModel",
      "settingsViewModel",
    ],
    elements: ["#janus_webcam_container"]
  });
});
