# coding=utf-8
from __future__ import absolute_import

__author__ = "Gina Häußge <osd@foosel.net>"
__license__ = 'GNU Affero General Public License http://www.gnu.org/licenses/agpl.html'
__copyright__ = "Copyright (C) 2014 The OctoPrint Project - Released under terms of the AGPLv3 License"

from flask import request, jsonify, make_response, url_for

from octoprint.filemanager.destinations import FileDestinations
from octoprint.settings import settings, valid_boolean_trues
from octoprint.server import printer, fileManager, slicingManager, eventManager, NO_CONTENT
from octoprint.server.util.flask import restricted_access, get_json_command_from_request
from octoprint.server.api import api
from octoprint.events import Events
import octoprint.filemanager
import octoprint.filemanager.util
import octoprint.slicing

import psutil


#~~ GCODE file handling


@api.route("/files", methods=["GET"])
def readGcodeFiles():
	filter = None
	recursive = False
	if "filter" in request.values:
		filter = request.values["filter"]

	if "recursive" in request.values:
		recursive = request.values["recursive"] == 'true'

	files = _getFileList(FileDestinations.LOCAL, filter=filter, recursive=recursive)
	files.extend(_getFileList(FileDestinations.SDCARD))

	usage = psutil.disk_usage(settings().getBaseFolder("uploads"))
	return jsonify(files=files, free=usage.free, total=usage.total)


@api.route("/files/<string:origin>", methods=["GET"])
def readGcodeFilesForOrigin(origin):
	if origin not in [FileDestinations.LOCAL, FileDestinations.SDCARD]:
		return make_response("Unknown origin: %s" % origin, 404)

	recursive = False
	if "recursive" in request.values:
		recursive = request.values["recursive"] == 'true'

	files = _getFileList(origin, recursive=recursive)

	if origin == FileDestinations.LOCAL:
		usage = psutil.disk_usage(settings().getBaseFolder("uploads"))
		return jsonify(files=files, free=usage.free, total=usage.total)
	else:
		return jsonify(files=files)


def _getFileDetails(origin, path):
	files = _getFileList(origin, recursive=True)
	path = path.split('/')

	def recursive_get_filedetails(files, path):
		for file in files:
			if file["name"] == path[0]:
				if len(path) > 1:
					return recursive_get_filedetails(file["children"], path[1:])
				else:
					return file

		return None

	return recursive_get_filedetails(files, path)


def _getFileList(origin, filter=None, recursive=False):
	if origin == FileDestinations.SDCARD:
		sdFileList = printer.get_sd_files()

		files = []
		if sdFileList is not None:
			for sdFile, sdSize in sdFileList:
				file = {
					"type": "machinecode",
					"name": sdFile,
					"origin": FileDestinations.SDCARD,
					"refs": {
						"resource": url_for(".readGcodeFile", target=FileDestinations.SDCARD, filename=sdFile, _external=True)
					}
				}
				if sdSize is not None:
					file.update({"size": sdSize})
				files.append(file)
	else:
		filter_func = None
		if filter:
			filter_func = lambda entry, entry_data: octoprint.filemanager.valid_file_type(entry, type=filter)

		files = fileManager.list_files(origin, filter=filter_func, recursive=recursive)[origin].values()

		def recursive_analysis(files, path):
			for file in files:
				file["origin"] = FileDestinations.LOCAL

				if file["type"] == "folder":
					file["children"] = recursive_analysis(file["children"].values(), path + file["name"] + "/")

				if "analysis" in file and octoprint.filemanager.valid_file_type(file["name"], type="gcode"):
					file["gcodeAnalysis"] = file["analysis"]
					del file["analysis"]

				if "history" in file and octoprint.filemanager.valid_file_type(file["name"], type="gcode"):
					# convert print log
					history = file["history"]
					del file["history"]
					success = 0
					failure = 0
					last = None
					for entry in history:
						success += 1 if "success" in entry and entry["success"] else 0
						failure += 1 if "success" in entry and not entry["success"] else 0
						if not last or ("timestamp" in entry and "timestamp" in last and entry["timestamp"] > last["timestamp"]):
							last = entry
					if last:
						prints = dict(
							success=success,
							failure=failure,
							last=dict(
								success=last["success"],
								date=last["timestamp"]
							)
						)
						if "printTime" in last:
							prints["last"]["printTime"] = last["printTime"]
						file["prints"] = prints

				file.update({
					"refs": {
						"resource": url_for(".readGcodeFile", target=FileDestinations.LOCAL, filename=path + file["name"], _external=True),
						"download": url_for("index", _external=True) + "downloads/files/" + FileDestinations.LOCAL + "/" + path + file["name"]
					}
				})

			return files

		files = recursive_analysis(files, "")

	return files


def _verifyFileExists(origin, filename):
	if origin == FileDestinations.SDCARD:
		return filename in map(lambda x: x[0], printer.get_sd_files())
	else:
		return fileManager.file_exists(origin, filename)


def _verifyFolderExists(origin, foldername):
	if origin == FileDestinations.SDCARD:
		return False
	else:
		return fileManager.folder_exists(origin, foldername)


def _verifyFolderNotBusy(target, foldername):
	busy_files = fileManager.get_busy_files()
	for item in busy_files:
		if target == item[0] and fileManager.file_in_path(target, foldername, item[1]):
			return False

	return True

@api.route("/files/<string:target>", methods=["POST"])
@restricted_access
def uploadGcodeFile(target):
	input_name = "file"
	input_upload_name = input_name + "." + settings().get(["server", "uploads", "nameSuffix"])
	input_upload_path = input_name + "." + settings().get(["server", "uploads", "pathSuffix"])
	if input_upload_name in request.values and input_upload_path in request.values:
		if not target in [FileDestinations.LOCAL, FileDestinations.SDCARD]:
			return make_response("Unknown target: %s" % target, 404)

		upload = octoprint.filemanager.util.DiskFileWrapper(request.values[input_upload_name], request.values[input_upload_path])

		# Store any additional user data the caller may have passed.
		userdata = None
		if "userdata" in request.values:
			import json
			try:
				userdata = json.loads(request.values["userdata"])
			except:
				return make_response("userdata contains invalid JSON", 400)

		if target == FileDestinations.SDCARD and not settings().getBoolean(["feature", "sdSupport"]):
			return make_response("SD card support is disabled", 404)

		sd = target == FileDestinations.SDCARD
		selectAfterUpload = "select" in request.values.keys() and request.values["select"] in valid_boolean_trues
		printAfterSelect = "print" in request.values.keys() and request.values["print"] in valid_boolean_trues

		if sd:
			# validate that all preconditions for SD upload are met before attempting it
			if not (printer.is_operational() and not (printer.is_printing() or printer.is_paused())):
				return make_response("Can not upload to SD card, printer is either not operational or already busy", 409)
			if not printer.is_sd_ready():
				return make_response("Can not upload to SD card, not yet initialized", 409)

		# determine current job
		currentFilename = None
		currentFullPath = None
		currentOrigin = None
		currentJob = printer.get_current_job()
		if currentJob is not None and "file" in currentJob.keys():
			currentJobFile = currentJob["file"]
			if currentJobFile is not None and "name" in currentJobFile.keys() and "origin" in currentJobFile.keys() and currentJobFile["name"] is not None and currentJobFile["origin"] is not None:
				currentPath, currentFilename = fileManager.sanitize(currentJobFile["origin"], currentJobFile["name"])
				currentFullPath = fileManager.join_path(target, currentPath, currentFilename)
				currentOrigin = currentJobFile["origin"]

		# determine future filename of file to be uploaded, abort if it can't be uploaded
		try:
			futurePath, futureFilename = fileManager.sanitize(target, upload.filename)
		except:
			futurePath = None
			futureFilename = None

		if futureFilename is None:
			return make_response("Can not upload file %s, wrong format?" % upload.filename, 415)

		if "path" in request.values:
			futurePath = fileManager.sanitize_path(target, request.values["path"])

		futureFullPath = fileManager.join_path(target, futurePath, futureFilename)

		# prohibit overwriting currently selected file while it's being printed
		if futureFullPath == currentFullPath and target == currentOrigin and printer.is_printing() or printer.is_paused():
			return make_response("Trying to overwrite file that is currently being printed: %s" % currentFilename, 409)

		def fileProcessingFinished(filename, absFilename, destination):
			"""
			Callback for when the file processing (upload, optional slicing, addition to analysis queue) has
			finished.

			Depending on the file's destination triggers either streaming to SD card or directly calls selectAndOrPrint.
			"""

			if destination == FileDestinations.SDCARD and octoprint.filemanager.valid_file_type(filename, "gcode"):
				return filename, printer.add_sd_file(filename, absFilename, selectAndOrPrint)
			else:
				selectAndOrPrint(filename, absFilename, destination)
				return filename

		def selectAndOrPrint(filename, absFilename, destination):
			"""
			Callback for when the file is ready to be selected and optionally printed. For SD file uploads this is only
			the case after they have finished streaming to the printer, which is why this callback is also used
			for the corresponding call to addSdFile.

			Selects the just uploaded file if either selectAfterUpload or printAfterSelect are True, or if the
			exact file is already selected, such reloading it.
			"""
			if octoprint.filemanager.valid_file_type(added_file, "gcode") and (selectAfterUpload or printAfterSelect or (currentFilename == filename and currentOrigin == destination)):
				printer.select_file(absFilename, destination == FileDestinations.SDCARD, printAfterSelect)

		added_file = fileManager.add_file(FileDestinations.LOCAL, futureFullPath, upload, allow_overwrite=True)
		if added_file is None:
			return make_response("Could not upload the file %s" % upload.filename, 500)
		if octoprint.filemanager.valid_file_type(added_file, "stl"):
			filename = added_file
			done = True
		else:
			filename = fileProcessingFinished(added_file, fileManager.path_on_disk(FileDestinations.LOCAL, added_file), target)
			done = True

		if userdata is not None:
			# upload included userdata, add this now to the metadata
			fileManager.set_additional_metadata(FileDestinations.LOCAL, added_file, "userdata", userdata)

		sdFilename = None
		if isinstance(filename, tuple):
			filename, sdFilename = filename

		eventManager.fire(Events.UPLOAD, {"file": filename, "target": target})

		files = {}
		location = url_for(".readGcodeFile", target=FileDestinations.LOCAL, filename=filename, _external=True)
		files.update({
			FileDestinations.LOCAL: {
				"name": filename,
				"origin": FileDestinations.LOCAL,
				"refs": {
					"resource": location,
					"download": url_for("index", _external=True) + "downloads/files/" + FileDestinations.LOCAL + "/" + filename
				}
			}
		})

		if sd and sdFilename:
			location = url_for(".readGcodeFile", target=FileDestinations.SDCARD, filename=sdFilename, _external=True)
			files.update({
				FileDestinations.SDCARD: {
					"name": sdFilename,
					"origin": FileDestinations.SDCARD,
					"refs": {
						"resource": location
					}
				}
			})

		r = make_response(jsonify(files=files, done=done), 201)
		r.headers["Location"] = location
		return r
	else:
		if "foldername" not in request.json:
			return make_response("No path information or no file included", 409)

		if not target in [FileDestinations.LOCAL]:
			return make_response("Unknown target: %s" % target, 404)

		futurePath, futureName = fileManager.sanitize(target, request.json["foldername"])
		futureFullPath = fileManager.join_path(target, futurePath, futureName)
		if octoprint.filemanager.valid_file_type(futureName):
			return make_response("Can't create a folder named %s, please try another name" % futureName, 409)

		added_folder = fileManager.add_folder(target, futureFullPath)
		if added_folder is None:
			return make_response("Could not create folder %s" % futureName, 500)

	return NO_CONTENT


@api.route("/files/<string:target>/<path:filename>", methods=["GET"])
def readGcodeFile(target, filename):
	if not target in [FileDestinations.LOCAL, FileDestinations.SDCARD]:
		return make_response("Unknown target: %s" % target, 404)

	file = _getFileDetails(target, filename)
	if not file:
		return make_response("File not found on '%s': %s" % (target, filename), 404)

	return jsonify(file)


@api.route("/files/<string:target>/<path:filename>", methods=["POST"])
@restricted_access
def gcodeFileCommand(filename, target):
	if not target in [FileDestinations.LOCAL, FileDestinations.SDCARD]:
		return make_response("Unknown target: %s" % target, 404)

	# valid file commands, dict mapping command name to mandatory parameters
	valid_commands = {
		"select": [],
		"slice": [],
		"copy": ["destination"],
		"move": ["destination"]
	}

	command, data, response = get_json_command_from_request(request, valid_commands)
	if response is not None:
		return response

	if command == "select":
		if not _verifyFileExists(target, filename):
			return make_response("File not found on '%s': %s" % (target, filename), 404)

		# selects/loads a file
		if not octoprint.filemanager.valid_file_type(filename, type="machinecode"):
			return make_response("Cannot select {filename} for printing, not a machinecode file".format(**locals()), 415)

		printAfterLoading = False
		if "print" in data.keys() and data["print"] in valid_boolean_trues:
			if not printer.is_operational():
				return make_response("Printer is not operational, cannot directly start printing", 409)
			printAfterLoading = True

		sd = False
		if target == FileDestinations.SDCARD:
			filenameToSelect = filename
			sd = True
		else:
			filenameToSelect = fileManager.path_on_disk(target, filename)
		printer.select_file(filenameToSelect, sd, printAfterLoading)

	elif command == "slice":
		if not _verifyFileExists(target, filename):
			return make_response("File not found on '%s': %s" % (target, filename), 404)

		try:
			if "slicer" in data:
				slicer = data["slicer"]
				del data["slicer"]
				slicer_instance = slicingManager.get_slicer(slicer)

			elif "cura" in slicingManager.registered_slicers:
				slicer = "cura"
				slicer_instance = slicingManager.get_slicer("cura")

			else:
				return make_response("Cannot slice {filename}, no slicer available".format(**locals()), 415)
		except octoprint.slicing.UnknownSlicer as e:
			return make_response("Slicer {slicer} is not available".format(slicer=e.slicer), 400)

		if not octoprint.filemanager.valid_file_type(filename, type="stl"):
			return make_response("Cannot slice {filename}, not an STL file".format(**locals()), 415)

		if slicer_instance.get_slicer_properties()["same_device"] and (printer.is_printing() or printer.is_paused()):
			# slicer runs on same device as OctoPrint, slicing while printing is hence disabled
			return make_response("Cannot slice on {slicer} while printing due to performance reasons".format(**locals()), 409)

		if "gcode" in data and data["gcode"]:
			gcode_name = data["gcode"]
			del data["gcode"]
		else:
			import os
			name, _ = os.path.splitext(filename)
			gcode_name = name + ".gco"

		# prohibit overwriting the file that is currently being printed
		currentOrigin, currentFilename = _getCurrentFile()
		if currentFilename == gcode_name and currentOrigin == target and (printer.is_printing() or printer.is_paused()):
			make_response("Trying to slice into file that is currently being printed: %s" % gcode_name, 409)

		if "profile" in data.keys() and data["profile"]:
			profile = data["profile"]
			del data["profile"]
		else:
			profile = None

		if "printerProfile" in data.keys() and data["printerProfile"]:
			printerProfile = data["printerProfile"]
			del data["printerProfile"]
		else:
			printerProfile = None

		if "position" in data.keys() and data["position"] and isinstance(data["position"], dict) and "x" in data["position"] and "y" in data["position"]:
			position = data["position"]
			del data["position"]
		else:
			position = None

		select_after_slicing = False
		if "select" in data.keys() and data["select"] in valid_boolean_trues:
			if not printer.is_operational():
				return make_response("Printer is not operational, cannot directly select for printing", 409)
			select_after_slicing = True

		print_after_slicing = False
		if "print" in data.keys() and data["print"] in valid_boolean_trues:
			if not printer.is_operational():
				return make_response("Printer is not operational, cannot directly start printing", 409)
			select_after_slicing = print_after_slicing = True

		override_keys = [k for k in data if k.startswith("profile.") and data[k] is not None]
		overrides = dict()
		for key in override_keys:
			overrides[key[len("profile."):]] = data[key]

		def slicing_done(target, gcode_name, select_after_slicing, print_after_slicing):
			if select_after_slicing or print_after_slicing:
				sd = False
				if target == FileDestinations.SDCARD:
					filenameToSelect = gcode_name
					sd = True
				else:
					filenameToSelect = fileManager.path_on_disk(target, gcode_name)
				printer.select_file(filenameToSelect, sd, print_after_slicing)

		try:
			fileManager.slice(slicer, target, filename, target, gcode_name,
			                  profile=profile,
			                  printer_profile_id=printerProfile,
			                  position=position,
			                  overrides=overrides,
			                  callback=slicing_done,
			                  callback_args=(target, gcode_name, select_after_slicing, print_after_slicing))
		except octoprint.slicing.UnknownProfile:
			return make_response("Profile {profile} doesn't exist".format(**locals()), 400)

		files = {}
		location = url_for(".readGcodeFile", target=target, filename=gcode_name, _external=True)
		result = {
			"name": gcode_name,
			"origin": FileDestinations.LOCAL,
			"refs": {
				"resource": location,
				"download": url_for("index", _external=True) + "downloads/files/" + target + "/" + gcode_name
			}
		}

		r = make_response(jsonify(result), 202)
		r.headers["Location"] = location
		return r

	elif command == "copy" or command == "move":
		# Copy and move are only possible on local storage
		if not target in [FileDestinations.LOCAL]:
			return make_response("Unknown target: %s" % target, 404)

		if not _verifyFileExists(target, filename) and not _verifyFolderExists(target, filename):
			return make_response("File/Folder not found on '%s': %s" % (target, filename), 404)

		overwrite = data["overwrite"] if "overwrite" in data else False
		destination = data["destination"]

		if _verifyFolderExists(target, destination):
			path, name = fileManager.split_path(target, filename)
			destination = fileManager.join_path(target, destination, name)

		if fileManager.file_exists(target, destination) and not overwrite:
			return make_response("File already exists and overwrite is prohibited: %s" % filename, 409)

		if command == "copy":
			if fileManager.file_exists(target, filename):
				fileManager.copy_file(target, filename, destination, overwrite)
			elif fileManager.folder_exists(target, filename):
				fileManager.copy_folder(target, filename, destination)
		elif command == "move":
			# prohibit deleting or moving files that are currently in use
			currentOrigin, currentFilename = _getCurrentFile()

			if currentFilename is not None and fileManager.file_in_path(target, filename, currentFilename) and currentOrigin == target and (printer.is_printing() or printer.is_paused()):
				return make_response("Trying to delete a folder that contains a file that is currently being printed: %s" % filename, 409)

			if not _verifyFolderNotBusy(target, filename):
				return make_response("Trying to delete a folder that contains a file that is currently in use: %s" % filename, 409)

			# deselect the file if it's currently selected
			if currentFilename is not None and filename == currentFilename:
				printer.unselect_file()

			if fileManager.file_exists(target, filename):
				fileManager.move_file(target, filename, destination, overwrite)
			elif fileManager.folder_exists(target, filename):
				fileManager.move_folder(target, filename, destination, overwrite)

	return NO_CONTENT


@api.route("/files/<string:target>/<path:filename>", methods=["DELETE"])
@restricted_access
def deleteGcodeFile(filename, target):
	if not _verifyFileExists(target, filename) and not _verifyFolderExists(target, filename):
		return make_response("File/Folder not found on '%s': %s" % (target, filename), 404)

	if _verifyFileExists(target, filename):
		if not target in [FileDestinations.LOCAL, FileDestinations.SDCARD]:
			return make_response("Unknown target: %s" % target, 404)

		# prohibit deleting files that are currently in use
		currentOrigin, currentFilename = _getCurrentFile()

		if currentFilename is not None and currentFilename == filename and currentOrigin == target and (printer.is_printing() or printer.is_paused()):
			return make_response("Trying to delete file that is currently being printed: %s" % filename, 409)

		if not _verifyFolderNotBusy(target, filename):
			return make_response("Trying to delete a file that is currently in use: %s" % filename, 409)

		# deselect the file if it's currently selected
		if currentFilename is not None and filename == currentFilename:
			printer.unselect_file()

		# delete it
		if target == FileDestinations.SDCARD:
			printer.delete_sd_file(filename)
		else:
			fileManager.remove_file(target, filename)

	elif _verifyFolderExists(target, filename):
		if not target in [FileDestinations.LOCAL]:
			return make_response("Unknown target: %s" % target, 404)

		folderpath = filename
		# prohibit deleting folders that are currently in use
		currentOrigin, currentFilename = _getCurrentFile()

		if currentFilename is not None and fileManager.file_in_path(target, folderpath, currentFilename) and currentOrigin == target and (printer.is_printing() or printer.is_paused()):
			return make_response("Trying to delete a folder that contains a file that is currently being printed: %s" % folderpath, 409)

		if not _verifyFolderNotBusy(target, folderpath):
			return make_response("Trying to delete a folder that contains a file that is currently in use: %s" % folderpath, 409)

		# deselect the file if it's currently selected
		if currentFilename is not None and fileManager.file_in_path(target, folderpath, currentFilename):
			printer.unselect_file()

		# delete it
		fileManager.remove_folder(target, folderpath)

	return NO_CONTENT

def _getCurrentFile():
	currentJob = printer.get_current_job()
	if currentJob is not None and "file" in currentJob.keys() and "name" in currentJob["file"] and "origin" in currentJob["file"]:
		return currentJob["file"]["origin"], currentJob["file"]["name"]
	else:
		return None, None


class WerkzeugFileWrapper(octoprint.filemanager.util.AbstractFileWrapper):
	"""
	A wrapper around a Werkzeug ``FileStorage`` object.

	Arguments:
	    file_obj (werkzeug.datastructures.FileStorage): The Werkzeug ``FileStorage`` instance to wrap.

	.. seealso::

	   `werkzeug.datastructures.FileStorage <http://werkzeug.pocoo.org/docs/0.10/datastructures/#werkzeug.datastructures.FileStorage>`_
	        The documentation of Werkzeug's ``FileStorage`` class.
	"""
	def __init__(self, file_obj):
		octoprint.filemanager.util.AbstractFileWrapper.__init__(self, file_obj.filename)
		self.file_obj = file_obj

	def save(self, path):
		"""
		Delegates to ``werkzeug.datastructures.FileStorage.save``
		"""
		self.file_obj.save(path)

	def stream(self):
		"""
		Returns ``werkzeug.datastructures.FileStorage.stream``
		"""
		return self.file_obj.stream
