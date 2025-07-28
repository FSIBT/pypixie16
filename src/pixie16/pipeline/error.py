
class Error(Exception):

	def __init__(self, type, msg, line):
		self.type = type
		self.msg = msg
		self.line = line
