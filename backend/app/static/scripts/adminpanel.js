function admin_alert(message) {
  var el = document.getElementById('admin_alert');
  if (el) el.innerHTML = message;
}

function toggleManualCorrection() {
  var el = document.getElementById('manual_correction');
  if (el) {
    el.style.display = el.style.display === 'none' ? 'block' : 'none';
  }
}

function getGameId() {
  var game = document.getElementById('UUID');
  var gameid = game.innerHTML;
  return gameid.replace(/['"]+/g, '');
}

function getMyId() {
  return parseInt(localStorage.getItem('id'));
}

function isMyAdmin(game) {
  var myId = getMyId();
  return game && game.Admins && game.Admins.indexOf(myId) !== -1;
}

function delete_player() {
  if (confirm('Bist du sicher das du den Spieler entfernen moechtest?')) {
    var gameid = getGameId();
    var delete_player = document.getElementById('select_delete_player');
    var user_id = delete_player.options[delete_player.selectedIndex].value;

    var xhttp = new XMLHttpRequest();
    xhttp.open("DELETE", "/api/game/" + gameid + "/user/" + user_id);
    xhttp.setRequestHeader("Content-Type", "application/json");
    xhttp.onreadystatechange = function () {
      if (xhttp.readyState == XMLHttpRequest.DONE) {
        if (xhttp.status != 200) {
          try {
            var res = JSON.parse(xhttp.responseText);
            admin_alert(res.Message);
          } catch (e) {
            admin_alert('Fehler');
          }
        }
        // H2: No more window.location.reload() - refresh_game handles it via socket
      }
    };
    xhttp.send();
  }
}

function sort_dice() {
  var gameid = getGameId();
  var myId = getMyId();
  var xhttp = new XMLHttpRequest();
  xhttp.open("PUT", "/api/game/" + gameid + "/sort");
  xhttp.setRequestHeader("Content-Type", "application/json");
  xhttp.onreadystatechange = function () {
    if (xhttp.readyState == XMLHttpRequest.DONE) {
      if (xhttp.status != 200) {
        try {
          var res = JSON.parse(xhttp.responseText);
          admin_alert('' + res.Message);
        } catch (e) {
          admin_alert('Fehler');
        }
      }
    }
  }
  xhttp.send(JSON.stringify({ admin_id: myId }));
}

function toggle_admin_action() {
  var gameid = getGameId();
  var choose_admin_el = document.getElementById('select_choose_admin');
  var target_id = choose_admin_el.options[choose_admin_el.selectedIndex].value;
  var myId = getMyId();

  if (confirm('Moechtest du diesen Spieler zum Admin ernennen?')) {
    var xhttp = new XMLHttpRequest();
    xhttp.open("POST", "/api/game/" + gameid + "/user/" + target_id + "/toggle_admin");
    xhttp.setRequestHeader("Content-Type", "application/json");
    xhttp.onreadystatechange = function () {
      if (xhttp.readyState == XMLHttpRequest.DONE) {
        if (xhttp.status != 200) {
          try {
            var res = JSON.parse(xhttp.responseText);
            admin_alert(res.Message);
          } catch (e) {
            admin_alert('Fehler');
          }
        }
        // H2: No more window.location.reload()
      }
    }
    xhttp.send(JSON.stringify({ requester_id: myId }));
  }
}

// Legacy choose_admin function (kept for backward compat)
function choose_admin() {
  toggle_admin_action();
}

function back_to_waiting() {
  if (confirm('Bist du sicher, dass du zurück zum Warteraum willst? Die Runde startet von vorne!')) {
    var gameid = getGameId();
    var xhttp = new XMLHttpRequest();
    xhttp.open("POST", "/api/game/" + gameid + "/back");
    xhttp.setRequestHeader("Content-Type", "application/json");
    xhttp.onreadystatechange = function () {
      if (xhttp.readyState == XMLHttpRequest.DONE) {
        if (xhttp.status != 201) {
          try {
            var res = JSON.parse(xhttp.responseText);
            admin_alert('' + res.Message);
          } catch (e) {
            admin_alert('Fehler');
          }
        }
      }
    }
    xhttp.send(JSON.stringify({}));
  }
}

function transfer_chips() {
  var gameid = getGameId();
  var myId = getMyId();
  var xhttp = new XMLHttpRequest();

  var stack_count = document.getElementById('stack_count_id');
  var count = stack_count.value;
  var transfer_source = document.getElementById('transfer_source');
  var source = transfer_source.options[transfer_source.selectedIndex].value;
  var transfer_target = document.getElementById('transfer_target');
  var target = transfer_target.options[transfer_target.selectedIndex].value;

  xhttp.open("POST", "/api/game/" + gameid + "/user/chips");
  xhttp.setRequestHeader("Content-Type", "application/json");
  xhttp.onreadystatechange = function () {
    if (xhttp.readyState == XMLHttpRequest.DONE) {
      if (xhttp.status != 200) {
        try {
          var res = JSON.parse(xhttp.responseText);
          admin_alert('' + res.Message);
        } catch (e) {
          admin_alert('Allgemeiner Fehler');
        }
      } else {
        var res = JSON.parse(xhttp.responseText);
        stack_count.value = 0;
        transfer_source.value = 'stack';
        admin_alert('' + res.Message);
      }
    }
  }
  if (source == 'stack') {
    xhttp.send(JSON.stringify({ count: parseInt(count), stack: true, target: parseInt(target), admin_id: myId }));
  } else if (source == 'schockaus') {
    xhttp.send(JSON.stringify({ schockaus: true, target: parseInt(target), admin_id: myId }));
  } else {
    xhttp.send(JSON.stringify({ count: parseInt(count), source: parseInt(source), target: parseInt(target), admin_id: myId }));
  }
}

function distribute() {
  var gameid = getGameId();
  document.getElementById('distribute_btn').disabled = true;
  var xhttp = new XMLHttpRequest();
  xhttp.open("POST", "/api/game/" + gameid + "/distribute");
  xhttp.setRequestHeader("Content-Type", "application/json");
  xhttp.onreadystatechange = function () {
    if (xhttp.readyState == XMLHttpRequest.DONE) {
      if (xhttp.status != 200) {
        // Silently ignore – another player likely already distributed.
        // The socket reload_game event will update the UI correctly.
      }
    }
  };
  xhttp.send(JSON.stringify({}));
}

function vote_reveal_all() {
  var gameid = getGameId();
  var myId = getMyId();
  var xhttp = new XMLHttpRequest();
  xhttp.open("POST", "/api/game/" + gameid + "/vote_reveal");
  xhttp.setRequestHeader("Content-Type", "application/json");
  xhttp.onreadystatechange = function () {
    if (xhttp.readyState == XMLHttpRequest.DONE) {
      if (xhttp.status != 200) {
        try {
          var res = JSON.parse(xhttp.responseText);
          alert(res.Message);
        } catch (e) {
          alert('Fehler');
        }
      }
    }
  };
  xhttp.send(JSON.stringify({ requester_id: myId }));
}

function toggle_leave(userId) {
  var myId = getMyId();
  // Check current game state from last known data
  var gameid = getGameId();

  var xhttp = new XMLHttpRequest();
  xhttp.open("POST", "/api/game/" + gameid + "/user/" + userId + "/mark_leave");
  xhttp.setRequestHeader("Content-Type", "application/json");
  xhttp.onreadystatechange = function () {
    if (xhttp.readyState == XMLHttpRequest.DONE) {
      if (xhttp.status != 200) {
        try {
          var res = JSON.parse(xhttp.responseText);
          alert(res.Message);
        } catch (e) {
          alert('Fehler');
        }
      }
    }
  };
  xhttp.send(JSON.stringify({ requester_id: myId }));
}

function mark_lobby() {
  var gameid = getGameId();
  var myId = getMyId();
  var xhttp = new XMLHttpRequest();
  xhttp.open("POST", "/api/game/" + gameid + "/mark_lobby");
  xhttp.setRequestHeader("Content-Type", "application/json");
  xhttp.onreadystatechange = function () {
    if (xhttp.readyState == XMLHttpRequest.DONE) {
      if (xhttp.status != 200) {
        try {
          var res = JSON.parse(xhttp.responseText);
          alert(res.Message);
        } catch (e) {
          alert('Fehler');
        }
      }
    }
  };
  xhttp.send(JSON.stringify({ requester_id: myId }));
}

function showRules() {
  document.getElementById('rulesModal').style.display = 'block';
}

function joinMidGame() {
  var gameid = getGameId();
  var nameInput = document.getElementById('join_name');
  var joinBtn = document.getElementById('join_btn');
  var username = nameInput.value.trim();
  if (!username) {
    alert('Bitte einen Namen eingeben');
    return;
  }
  if (joinBtn) joinBtn.disabled = true;
  nameInput.disabled = true;
  var xhttp = new XMLHttpRequest();
  xhttp.open("POST", "/api/game/" + gameid + "/user");
  xhttp.setRequestHeader("Content-Type", "application/json");
  xhttp.onreadystatechange = function () {
    if (xhttp.readyState == XMLHttpRequest.DONE) {
      var res = JSON.parse(xhttp.responseText);
      if (xhttp.status != 200) {
        alert('Fehler: ' + res.Message + '\nSeite wird neu geladen.');
        location.reload();
      } else {
        localStorage.setItem('name', username);
        for (var num in res.User) {
          var juser = res.User[num];
          if (juser['Name'] == username) {
            localStorage.setItem('id', juser['Id']);
          }
        }
        // Update user display
        var userEl = document.getElementById('ownuser');
        if (userEl) userEl.innerHTML = "Spieler: " + username;
        // Trigger refresh
        initial_game_data();
      }
    }
  }
  var payload = { name: username };
  var oldId = localStorage.getItem('id');
  if (oldId) payload.reconnect_id = parseInt(oldId);
  xhttp.send(JSON.stringify(payload));
}

// H2: Update admin panel select lists dynamically
function updatePlayerSelects(game) {
  var myId = getMyId();
  var selectIds = ['transfer_source_user', 'transfer_target_user'];
  selectIds.forEach(function (selectId) {
    var el = document.getElementById(selectId);
    if (!el) return;
    // Clear existing options
    while (el.options && el.options.length > 0) { el.remove(0); }
    // For optgroups, clear children
    while (el.firstChild) { el.removeChild(el.firstChild); }
    // Repopulate from game.User (exclude own user)
    game.User.forEach(function (u) {
      if (!u.Pending_Join) {
        var opt = document.createElement('option');
        opt.value = u.Id;
        opt.innerHTML = u.Name;
        el.appendChild(opt);
      }
    });
  });

  selectIds = ['select_delete_player', 'select_choose_admin'];
  selectIds.forEach(function (selectId) {
    var el = document.getElementById(selectId);
    if (!el) return;
    // Clear existing options
    while (el.options && el.options.length > 0) { el.remove(0); }
    // For optgroups, clear children
    while (el.firstChild) { el.removeChild(el.firstChild); }
    // Repopulate from game.User (exclude own user)
    game.User.forEach(function (u) {
      if (!u.Pending_Join && u.Id !== myId) {
        var opt = document.createElement('option');
        opt.value = u.Id;
        opt.innerHTML = u.Name;
        el.appendChild(opt);
      }
    });
  });

  // Update schockaus option label from ruleset
  if (game.Ruleset && game.Ruleset.rules) {
    var schockausOpt = document.querySelector('#transfer_source option[value="schockaus"]');
    if (schockausOpt) {
      for (var ri = 0; ri < game.Ruleset.rules.length; ri++) {
        if (game.Ruleset.rules[ri].chips === -1) {
          schockausOpt.textContent = game.Ruleset.rules[ri].name;
          break;
        }
      }
    }
  }

  // Update stack count options
  var selectionchips = document.getElementById('stack_count_id');
  if (selectionchips) {
    while (selectionchips.options.length > 1) { selectionchips.remove(1); }
    for (var i = 1; i <= game.Stack_Max; i++) {
      var exists = false;
      for (var j = 0; j < selectionchips.options.length; j++) {
        if (parseInt(selectionchips.options[j].value) === i) { exists = true; break; }
      }
      if (!exists) {
        var chipcount = document.createElement('option');
        chipcount.value = i;
        chipcount.innerHTML = i.toString();
        selectionchips.appendChild(chipcount);
      }
    }
  }
}
