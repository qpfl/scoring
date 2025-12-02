"""
Simple Offline Scorer
"""

import math


class Scorer:
    def __init__(self):
        """
        Initializer for Scorer class
        """
        self.team_score = 0
        self.opponent_score = 0

    def _quarterback(self) -> int:
        """
        Helper method to score a quarterback

        Returns:
            int: QB's total points for the week
        """
        print("Scoring quarterback")
        points = 0
        pyards = input("Passing Yards: ")
        points += math.floor(int(pyards) / 25)
        rush_yards = int(input("Rushing Yards: "))
        points += math.floor(rush_yards / 10)
        points += 6 * int(input("Total TDs: "))
        turnovers = 2 * int(input("Total turnovers: "))
        points -= turnovers
        if turnovers > 0:
            pick_fumble_six = int(input("Total turnovers returned for TDs: "))
            points -= 4 * pick_fumble_six
        go_further = str(input("Did your QB score another way? y/n: "))
        if go_further == "y":
            two_pt = int(input("Total two point conversions: "))
            points += two_pt * 2
            rec_yds = int(input("Receiving Yards: "))
            points += math.floor(rec_yds / 10)
        print(f"QB Score: {points}")
        print()
        return points

    def _runningback(self) -> int:
        """
        Helper method to score a running back

        Returns:
            int: RB's total points for the week
        """
        print("Scoring running back")
        points = 0
        rush_yards = input("Rushing Yards: ")
        if str.lower(rush_yards) == "scored":
            points = int(input("Points: "))
            return points
        points += math.floor(int(rush_yards) / 10)
        rec_yds = int(input("Receiving Yards: "))
        points += math.floor(rec_yds / 10)
        points += 6 * int(input("Total TDs: "))
        turnovers = 2 * int(input("Total turnovers: "))
        points -= turnovers
        if turnovers > 0:
            pick_fumble_six = int(input("Total turnovers returned for TDs: "))
            points -= 4 * pick_fumble_six
        go_further = str.lower(input("Did your RB score another way? y/n: "))
        if go_further == "y":
            pyards = int(input("Passing Yards: "))
            points += math.floor(pyards / 25)
            two_pt = int(input("Total two point conversions: "))
            points += two_pt * 2
        elif go_further != "n":
            print(f"Input {go_further} not recognized (y/n accepted). Please try again")
            points = self._runningback()
        print(f"RB Score: {points}")
        print()
        return points

    def _receiver_te(self, player_type: str) -> int:
        """
        Helper method to score a wide receiver or tight end

        Args:
            player_type (int): The player position

        Returns:
            int: WR/TE's points for the week
        """
        print(f"Scoring {str.upper(player_type)}")
        points = 0
        rec_yds = input("Receiving Yards: ")
        if str.lower(rec_yds) == "scored":
            points = int(input("Points: "))
            return points
        points += math.floor(int(rec_yds) / 10)
        points += 6 * int(input("Total TDs: "))
        turnovers = 2 * int(input("Total turnovers: "))
        points -= turnovers
        if turnovers > 0:
            pick_fumble_six = int(input("Total turnovers returned for TDs: "))
            points -= 4 * pick_fumble_six
        go_further = str.lower(input(f"Did your {str.upper(player_type)} score another way? y/n: "))
        if go_further == "y":
            rush_yards = int(input("Rushing Yards: "))
            points = math.floor(rush_yards / 10)
            pyards = int(input("Passing Yards: "))
            points += math.floor(pyards / 25)
            two_pt = int(input("Total two point conversions: "))
            points += two_pt * 2
        elif go_further != "n":
            print(f"Input {go_further} not recognized (y/n accepted). Please try again")
            points = self._runningback()
        print(f"{str.upper(player_type)} Score: {points}")
        print()
        return points

    def _kicker(self) -> int:
        """
        Helper method to score a kicker

        Returns:
            int: K's total points for the week
        """
        print("Scoring kicker")
        points = 0
        first = input("PATs made: ")
        if str.lower(first) == "scored":
            points = int(input("Points: "))
            return points
        else:
            points += int(first)
        points -= 2 * int(input("PATs missed: "))
        points += int(input("FGs 1-29 yards: "))
        points += 2 * int(input("FGs 30-49 yards: "))
        points += 3 * int(input("FGs 40-49 yards: "))
        points += 4 * int(input("FGs 50-59 yards: "))
        points += 5 * int(input("FGs 60-69 yards: "))
        points += 6 * int(input("FGs 70+ yards: "))
        points -= 1 * int(input("Field Goals missed: "))
        print(f"K Score: {points}")
        print()
        return points

    def _defense(self) -> int:
        """
        Helper method to score a defense/special teams

        Returns:
            int: D/ST's total points for the week
        """
        print("Scoring D/ST")
        points = 0
        points_allowed = input("Points Allowed: ")
        if str.lower(points_allowed) == "scored":
            points = int(input("Points: "))
            return points
        else:
            points_allowed = int(points_allowed)
        if points_allowed == 0:
            points += 8
        elif points_allowed <= 9:
            points += 6
        elif points_allowed <= 13:
            points += 4
        elif points_allowed <= 17:
            points += 2
        elif points_allowed <= 31:
            points += -2
        elif points_allowed <= 35:
            points += -4
        else:
            points += -6
        points += 2 * int(input("Turnovers: "))
        points += int(input("Sacks: "))
        points += 2 * int(input("Safeties: "))
        points += 2 * int(input("Blocked punt or FGs: "))
        points += int(input("Blocked PATs: "))
        points += 4 * int(input("Defensive TDs: "))
        print(f"D/ST Score: {points}")
        print()
        return points

    def _head_coach(self) -> int:
        """
        Helper method to score a head coach

        Returns:
            int: HC's total points for the week
        """
        print("Scoring head coach")
        points = 0
        win = str.lower(input("Coach Win? y/n: "))
        if str.lower(win) == "scored":
            points = int(input("Points: "))
            return points
        win_bool = True if win == "y" else False
        if win_bool:
            win_margin = int(input("Margin of Victory: "))
            if win_margin < 10:
                points += 2
            elif win_margin <= 19:
                points += 3
            else:
                points += 4
        else:
            loss_margin = int(input("Margin of Defeat: "))
            if loss_margin < 10:
                points -= 1
            elif loss_margin <= 20:
                points -= 2
            else:
                points -= 3
        print(f"HC Score: {points}")
        print()
        return points

    def _team_controller(self) -> int:
        """
        Helper method to score a full team

        Returns:
            int: team's total points
        """
        points = 0
        points += self._quarterback()
        points += self._runningback()
        points += self._runningback()
        points += self._receiver_te(player_type="wr")
        points += self._receiver_te(player_type="wr")
        points += self._receiver_te(player_type="te")
        points += self._kicker()
        points += self._defense()
        points += self._head_coach()
        return points

    def controller(self) -> tuple:
        """
        Controller method for the Scorer class

        Returns:
            tuple: (team score, opponent score), each defaults to 0 if mode not activated
        """
        print("QPFL Scorer Modes: (p) player, (t) team, (m) matchup")
        self.mode = str.lower(input("Choose mode (p, t, m): "))
        if self.mode == "p":
            player_count = int(input("How many players would you like to score: "))
            for i in range(player_count):
                print("Player Types: qb, rb, wr, te, k, def, hc")
                player_type = str.lower(input("Player Type: "))
                if player_type == "qb":
                    score = self._quarterback()
                elif player_type == "rb":
                    score = self._runningback()
                elif player_type == "wr" or player_type == "te":
                    score = self._receiver_te(player_type)
                elif player_type == "k":
                    score = self._kicker()
                elif player_type == "def":
                    score = self._defense()
                elif player_type == "hc":
                    score = self._head_coach()
                print(f"{str.upper(player_type)} Score: {score}")
        elif self.mode == "m":
            self.team_score = self._team_controller()
            self.opponent_score = self._team_controller()
            print(f"Team 1 Score: {self.team_score}")
            print(f"Team 2 Score: {self.opponent_score}")
        else:
            self.team_score = self._team_controller()
            print(f"Team Score: {self.team_score}")
        return (self.team_score, self.opponent_score)


if __name__ == "__main__":
    scorer = Scorer()
    scorer.controller()