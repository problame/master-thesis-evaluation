import copy

class Store:
	d = {}
	def add(self, configlabel, value):
		assert isinstance(configlabel, str)
		assert isinstance(value, str)
		l = self.d.get(configlabel, [])
		l.append(value)
		self.d[configlabel] = l

	def get_one(self, configlabel):
		assert isinstance(configlabel, str)
		l = self.d.get(configlabel, [])
		assert len(l) == 1
		return l[0]

	def get_all(self, configlabel):
		assert isinstance(configlabel, str)
		return self.d.get(configlabel, [])

	def get_first(self, configlabel):
		assert isinstance(configlabel, str)
		all = self.get_all(configlabel)
		assert len(all) >= 1
		return all[0]

	def to_dict(self):
		return copy.deepcopy(self.d)

	def from_dict(d):
		for k, v in d.items():
			assert isinstance(k, str)
			assert isinstance(v, list)
			for i in v:
				assert isinstance(i, str)
		s = Store()
		s.d = d
		return s


