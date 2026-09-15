var navigation = require('../utils/navigation')
Component({
  data: { selected: 0, hide: false, canExport: false, canDomestic: false },
  methods: {
    onTabTap: function (e) {
      navigation.open(Number(e.currentTarget.dataset.index) === 0 ? 'export' : 'domestic')
    }
  }
})
