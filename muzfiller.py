#!/usr/bin/env python

import pygtk
pygtk.require('2.0')
import gtk, os, gio, threading, shutil, glob, socket, sys, gobject, errno

class AlreadyRunning(RuntimeError):
	pass

class SocketError(RuntimeError):
	pass

class Client:
	def __init__(self, socket_file):
		self.socket_file = socket_file
	def check_exists(self):
		if os.path.exists(self.socket_file):
			s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
			try:
				s.connect(self.socket_file)
				s.close()
			except socket.error, (no, strerr):
				if no == errno.ECONNREFUSED:
					raise SocketError()
			return True
		else:
			return False

	def send_files(self, files):
		s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
		s.connect(self.socket_file)
		for file in files:
			s.send(file + '\n')
		s.close()

class SocketThread(threading.Thread, gobject.GObject):
	def __init__(self, socket_file):
		gobject.GObject.__init__(self)
		threading.Thread.__init__(self)
		self.socket_file = socket_file
		gobject.signal_new('files_received', SocketThread,
				gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE, (object, ))

	def stop(self):
		self.need_stop = True
		Client(self.socket_file).send_files([])
		self.join()

	def run(self):
		self.need_stop = False
		s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
		s.bind(self.socket_file)
		s.listen(1)
		while not self.need_stop:
			c = s.accept()[0]
			buf = c.recv(1024)
			data = ''
			while buf:
				data += buf
				buf = c.recv(1024)
			c.close()
			files = data.split()
			if len(files):
				self.emit("files_received", files)
		os.remove(self.socket_file)


class CopyThread(threading.Thread, gobject.GObject):
	TARGET_DIR = '/home/nailgun/tmp'
	COUNTER_END = 999999 

	def __init__(self):
		gobject.GObject.__init__(self)
		threading.Thread.__init__(self)
		self.new_files_event = threading.Event()
		self.current_file = 0
		self.counter_end = self.COUNTER_END
		# store format:
		# basename, src_path, dest_basename, dest_path
		self.muzstore = gtk.ListStore(str, str, str, str)
		self.copying = False
		gobject.signal_new('start_copy', CopyThread,
				gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE, ())

	def new_files_added(self):
		self.new_files_event.set()

	def stop(self):
		self.need_stop = True
		self.new_files_event.set()
		self.join()

	def resize_name(self, name):
		file_name_len = len(str(self.COUNTER_END))
		while len(name) < file_name_len:
			name = '0' + name
		return name

	def gen_filename(self, ext):
		file_name = self.resize_name(str(self.counter_end))
		while glob.glob(os.path.join(self.TARGET_DIR, file_name + '.*')):
			self.counter_end -= 1
			if self.counter_end < 0:
				raise RuntimeError('counter reached zero')
			file_name = self.resize_name(str(self.counter_end))
		return file_name + ext

	def run(self):
		self.need_stop = False
		while not self.need_stop:
			self.new_files_event.wait()
			self.new_files_event.clear()
			if self.need_stop:
				break
			try:
				iter = self.muzstore.get_iter(self.current_file)
			except ValueError:
				iter = None
			self.copying = True
			self.emit('start_copy')
			while iter:
				if self.need_stop:
					break
				src_path = self.muzstore.get_value(iter, 1)
				dest_basename = self.gen_filename(os.path.splitext(src_path)[1])
				dest_path = os.path.join(self.TARGET_DIR, dest_basename)
				self.muzstore.set(iter, 2, dest_basename, 3, dest_path)
				shutil.copy(src_path, dest_path)
				self.current_file += 1
				self.counter_end -= 1
				iter = self.muzstore.iter_next(iter)
			self.copying = False

class MuzFiller:
	TARGET_TYPE_TEXT = 1
	LIST_ACCEPT = [('text/plain', 0, TARGET_TYPE_TEXT)]
	SOCKET_NAME = '.muzfiller.sock'

	def destroy(self, widget, data=None):
		# TODO: message: copy in progress, please wait
		self.socket_thread.stop()
		self.copy_thread.stop()
		gtk.main_quit()

	def add_names(self, name_list):
		for src_name in name_list:
			src = gio.File(src_name)
			basename = src.get_basename()
			src_path = src.get_path()
			self.copy_thread.muzstore.append([basename, src_path, None, None])
		if len(name_list):
			self.copy_thread.new_files_added()

	def add_uris(self, uri_list):
		for src_uri in uri_list:
			src = gio.File(uri=src_uri)
			basename = src.get_basename()
			src_path = src.get_path()
			self.copy_thread.muzstore.append([basename, src_path, None, None])
		if len(uri_list):
			self.copy_thread.new_files_added()

	def file_drop(self, widget, context, x, y, selection, target, time):
		if target == self.TARGET_TYPE_TEXT:
			self.add_uris(selection.data.split())

	def show_info(self, treeview):
		cursor = treeview.get_cursor()
		if not cursor:
			self.info.set_text('click file to get info')
		else:
			it = self.copy_thread.muzstore.get_iter(cursor[0])
			src_path = self.copy_thread.muzstore.get_value(it, 1)
			self.info.set_text(src_path)

	def setup_ui(self):
		self.window = gtk.Window(gtk.WINDOW_TOPLEVEL)
		self.window.set_title("MuzFiller")
		self.window.set_border_width(8);

		self.listview = gtk.TreeView(self.copy_thread.muzstore)

		cell_file = gtk.CellRendererText()
		col_file = gtk.TreeViewColumn('Filename', cell_file)
		col_file.add_attribute(cell_file, 'text', 0)
		col_file.set_sort_column_id(0)

		cell_dest = gtk.CellRendererText()
		col_dest = gtk.TreeViewColumn('New filename', cell_dest)
		col_dest.add_attribute(cell_dest, 'text', 2)
		col_dest.set_sort_column_id(2)

		self.listview.append_column(col_file)
		self.listview.append_column(col_dest)
		self.listview.set_search_column(0)

		scrolled = gtk.ScrolledWindow()
		scrolled.set_shadow_type(gtk.SHADOW_ETCHED_IN)
		scrolled.set_policy(gtk.POLICY_NEVER, gtk.POLICY_AUTOMATIC)
		scrolled.add(self.listview)

		self.info = gtk.Label('click file to get info')
		self.progress = gtk.ProgressBar()

		box1 = gtk.VBox(False, 2)
		box1.pack_start(scrolled)
		box1.pack_start(self.info, False)
		box1.pack_start(self.progress, False)
		self.window.add(box1)

		self.listview.drag_dest_set(gtk.DEST_DEFAULT_ALL,
				self.LIST_ACCEPT, gtk.gdk.ACTION_DEFAULT | gtk.gdk.ACTION_MOVE)

		self.listview.connect('drag_data_received', self.file_drop)
		self.listview.connect('cursor_changed', self.show_info)
		self.window.connect("destroy", self.destroy)

		self.window.set_default_size(300, 200)

	def parse_args(self, redirect):
		if redirect:
			c = Client(self.socket_file)
			paths = []
			for name in sys.argv[1:]:
				f = gio.File(name)
				paths.append(f.get_uri())
			if len(paths):
				c.send_files(paths)
		else:
			if len(sys.argv) > 1:
				self.add_names(sys.argv[1:])

	def handle_received(self, thread, uris):
		self.add_uris(uris)

	def handle_start_copy(self, thread):
		gobject.idle_add(self.update_progress)

	def update_progress(self):
		cur = self.copy_thread.current_file
		try:
			iter = self.copy_thread.muzstore.get_iter(cur)
		except ValueError:
			self.progress.set_fraction(0)
			return

		# TODO: write total size in store (optimize)
		src_path, dest_path = self.copy_thread.muzstore.get(iter, 1, 3)
		total = os.path.getsize(src_path)
		try:
			size = os.path.getsize(dest_path)
		except OSError, err:
			if err[0] == errno.ENOENT:
				size = 0
			else:
				raise err
		self.progress.set_fraction(size / float(total))

		if self.copy_thread.copying:
			gobject.idle_add(self.update_progress)
		else:
			self.progress.set_fraction(0)

	def __init__(self):
		gtk.gdk.threads_init()

		home_path = os.path.expanduser('~')
		self.socket_file = os.path.join(home_path, self.SOCKET_NAME)

		try:
			redirect = Client(self.socket_file).check_exists()
		except SocketError:
			redirect = False
			os.remove(self.socket_file)

		if not redirect:
			self.copy_thread = CopyThread()

		self.parse_args(redirect)
		if redirect:
			raise AlreadyRunning()

		self.socket_thread = SocketThread(self.socket_file)
		self.socket_thread.connect('files_received', self.handle_received)
		self.copy_thread.connect('start_copy', self.handle_start_copy)

		self.setup_ui()
		self.copy_thread.start()
		self.socket_thread.start()

	def main(self):
		self.window.show_all()
		gtk.main()

if __name__ == "__main__":
	try:
		app = MuzFiller()
		app.main()
	except AlreadyRunning:
		pass
