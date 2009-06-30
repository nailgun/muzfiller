#!/usr/bin/env python

import pygtk
pygtk.require('2.0')
import gtk, os, gio, threading, shutil, glob
gtk.gdk.threads_init()

class CopyThread(threading.Thread):
	TARGET_DIR = '/home/nailgun/tmp'
	COUNTER_END = 999999 

	def __init__(self):
		threading.Thread.__init__(self)
		self.new_files_event = threading.Event()
		self.current_file = 0
		self.counter_end = self.COUNTER_END

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

			iter = self.muzstore.get_iter(self.current_file)
			while iter:
				if self.need_stop:
					break

				src_path = self.muzstore.get_value(iter, 1)
				dest_basename = self.gen_filename(os.path.splitext(src_path)[1])
				dest_path = os.path.join(self.TARGET_DIR, dest_basename)
				shutil.copy(src_path, dest_path)
				self.muzstore.set(iter, 2, dest_basename, 3, dest_path)
				self.current_file += 1
				self.counter_end -= 1
				iter = self.muzstore.iter_next(iter)

class MuzFiller:
	TARGET_TYPE_TEXT = 1
	LIST_ACCEPT = [('text/plain', 0, TARGET_TYPE_TEXT)]

	def destroy(self, widget, data=None):
		# TODO: message: copy in progress, please wait
		self.thread.stop()
		gtk.main_quit()

	def add_files(self, uri_list):
		for src_uri in uri_list:
			src = gio.File(uri=src_uri)
			basename = src.get_basename()
			src_path = src.get_path()
			self.thread.muzstore.append([basename, src_path, None, None])
		self.thread.new_files_added()

	def file_drop(self, widget, context, x, y, selection, target, time):
		if target == self.TARGET_TYPE_TEXT:
			self.add_files(selection.data.split())

	def show_info(self, treeview):
		cursor = treeview.get_cursor()
		if not cursor:
			self.info.set_text('click file to get info')
		else:
			it = self.thread.muzstore.get_iter(cursor[0])
			src_path = self.thread.muzstore.get_value(it, 1)
			self.info.set_text(src_path)

	def setup_ui(self):
		self.window = gtk.Window(gtk.WINDOW_TOPLEVEL)
		self.window.set_title("MuzFiller")
		self.window.set_border_width(8);

		# store format:
		# basename, src_path, dest_basename, dest_path
		self.thread.muzstore = gtk.ListStore(str, str, str, str)
		self.listview = gtk.TreeView(self.thread.muzstore)

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
		self.window.show_all()

	def __init__(self):
		self.thread = CopyThread()
		self.setup_ui()
		self.thread.start()

	def main(self):
		gtk.main()

if __name__ == "__main__":
	app = MuzFiller()
	app.main()
