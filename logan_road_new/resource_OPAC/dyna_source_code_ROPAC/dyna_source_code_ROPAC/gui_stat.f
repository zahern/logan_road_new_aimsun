      subroutine gui_stat(l)  
c  --
c  --
      use muc_mod
c  -- 
      Avg_speed=0.0
      Avg_speed_net=0.0
      Avg_speed_free=0.0
      nu_free=0
      nu_net=0

      if((l-1).eq.int_d) then
         close(800)
         open(file='fort.800', unit=800,status='unknown')
	endif
1010     format(10i5)
      write(800,'("==============================")')
      write(800,'("Current Time               :",f6.1)') (l-1)*tii
      write(800,'("Total # of Gen Vehs        :",i6)') jj

      write(800,'("Total # of Out Vehs        :",i6)') jj-numcars
c  --
c  -- jj-numcars is the number of vehicles went out of the network 
c  --
      write(800,'("Total # of In Vehs         :",i6)') numcars
c  --
c  -- numcars is the number of vehicles still in the network 
c  --
      tt=0.0
      if(jj.gt.0) TT = GuiTotalTime/jj
      write(800,'("Avg Travel Time All Vehs   :",f6.1)') tt 
c  -- GuiTotalTime is defined as the total time for all generated vehicles
c  -- It is calculated in the codes whenever the ttilnow is updated
c  -- tt is the average travel time for all vehicles
c  --
      if((jj-numcars).lt.1) then
       write(800,'("Avg Travel Time for out Veh:",f6.1)') 0.0
      else
       tt_out=triptime1/(jj-numcars)
      write(800,'("Avg Travel Time for out Veh:",f6.1)') tt_out 
      endif
c  --
c  -- tt_out is the average travel time for vehicles that went out of the network
c  -- triptime1 is calculated in get_veh_stat whenever a vehicle is out of network

      do j1=1,noofarcs
	  if (link_iden(j1) < 99) then
          avg_speed=avg_speed+v(j1)


! link_type 9 = hot on a freeway
! link_type 10 = hov on a freeway
!         if(link_iden(j1).eq.1) then
          if(link_iden(j1).eq.1.or.link_iden(j1).eq.9.
     +		or.link_iden(j1).eq.10) then
            avg_speed_free=avg_speed_free+v(j1)
            nu_free=nu_free+1
          else
            avg_speed_net=avg_speed_net+v(j1)
            nu_net=nu_net+1
          endif
	  endif
      enddo

      tot_avg = (avg_speed/noofarcs_org)*60.0

      write(800,'("Avg speed for all links    :",f6.1)') tot_avg 

c  --
c  -- tot_avg is the average speed for all links in the network
c  --
      if(nu_free.gt.0) then
        avg_free = (avg_speed_free/nu_free)*60.0
        write(800,'("Avg speed for freeways     :",f6.1)') avg_free
	else
        write(800,'("Avg speed for freeways     :",f6.1)') 0.0
	endif
c  --
c  -- avg_free is the average speed for freeway links in the network
c  --
      if(nu_net.gt.0) then
	  avg_net = (avg_speed_net/nu_net)*60.0
        write(800,'("Avg speed for arterials    :",f6.1)') avg_net
	else
        write(800,'("Avg speed for arterials    :",f6.1)') 0.0
	endif 
c  --
c  -- avg_net is the average speed for non-freeway links in the network
c  --
       time_min=(time_now)/60.0
c  --
c  -- time_min is the clock time inside the simulator in min.
c  --

100   format(i6)
101   format(f6.1)
102   format(f6.1)
   
      return
      end 
