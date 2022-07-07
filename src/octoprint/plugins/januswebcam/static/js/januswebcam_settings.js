$(function () {
  function JanusWebcamSettingsViewModel(parameters) {
    var self = this;

    self.loginState = parameters[0];
    self.settings = parameters[1];
    self.janusWebcam = parameters[2];

    self.onBeforeBinding = function () {
      self.webcamEnabled = self.settings.settings.webcam.webcamEnabled;

      self.flipH = self.settings.settings.plugins.januswebcam.flipH;
      self.flipV = self.settings.settings.plugins.januswebcam.flipV;
      self.rotate90 = self.settings.settings.plugins.januswebcam.rotate90;
      self.janusApiUrl = self.settings.settings.plugins.januswebcam.janusApiUrl;
      self.janusApiToken = self.settings.settings.plugins.januswebcam.janusApiToken;
      self.streamWebrtcIceServers = self.settings.settings.plugins.januswebcam.streamWebrtcIceServers;
      self.loading = self.janusWebcam.loading;
      self.active = self.janusWebcam.active;
      self.ready = self.janusWebcam.ready;

      self.updateStreamsList = self.janusWebcam.updateStreamsList;
      self.streams = self.janusWebcam.streams;
      self.startStream = self.janusWebcam.startStream;
      self.stopStream = self.janusWebcam.stopStream;
      self.selectedStreamId = self.janusWebcam.selectedStreamId;
      self.showStartButton = self.janusWebcam.showStartButton;
    };

    // self.getSelectedStreamText = function (item) {
    //   return item.description;
    // }

    // self.selectedStreamText = function (item) {
    //   return item.description;
    // }
  }

  OCTOPRINT_VIEWMODELS.push({
    construct: JanusWebcamSettingsViewModel,
    dependencies: ["loginStateViewModel", "settingsViewModel", "janusWebcamViewModel"],
    elements: ["#janus_webcam_settings"]
  });
});
